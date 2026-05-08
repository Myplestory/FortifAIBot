from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands
from dotenv import load_dotenv

import embeds
import generate
import llm
import parse
import scheduler
from commands import (
    analyze as analyze_cmd,
    confirm,
    session as session_cmd,
    stats as stats_cmd,
    transcript as transcript_cmd,
)

load_dotenv()
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("fortifai")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.dm_messages = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


# --- extracted command modules --------------------------------------------


transcript_cmd.register(tree)
analyze_cmd.register(tree)
stats_cmd.register(tree)
session_cmd.register(tree)


# --- /knowledgeharden ------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _split_csv(s: str | None) -> list[str]:
    if not s:
        return []
    return [tok.strip() for tok in s.split(",") if tok.strip()]


def _validate_args_against_meta(
    fields: list[str],
    topics: list[str],
    meta: dict[str, Any],
) -> str | None:
    fields_dict = meta.get("fields", {})
    bad_fields = [f for f in fields if f not in parse.CANONICAL_FIELDS or f not in fields_dict]
    if bad_fields:
        valid = ", ".join(f"`{k}`" for k in parse.CANONICAL_FIELDS.keys())
        return f"Unknown fields: {', '.join(bad_fields)}. Valid fields: {valid}."
    if topics:
        scope = fields if fields else list(parse.CANONICAL_FIELDS.keys())
        all_topics: set[str] = set()
        for slug in scope:
            for t in fields_dict.get(slug, {}).get("topics", []):
                all_topics.add(t)
        bad_topics = [t for t in topics if t not in all_topics]
        if bad_topics:
            sample = ", ".join(f"`{t}`" for t in sorted(all_topics)[:8]) or "(none yet — topics grow as questions generate)"
            return f"Unknown topics: {', '.join(bad_topics)}. Existing topics in scope: {sample}."
    return None


_DEFAULT_QUIZ_TIMEOUT = 1800.0
_COUNTDOWN_TICK_SECONDS = 30.0


async def _wait_for_thread_message(thread: discord.Thread, user: discord.abc.User, *, timeout: float = _DEFAULT_QUIZ_TIMEOUT) -> discord.Message:
    def _check(m: discord.Message) -> bool:
        return m.channel.id == thread.id and m.author.id == user.id and not m.author.bot

    return await bot.wait_for("message", check=_check, timeout=timeout)


async def _update_countdown_field(
    message: discord.Message,
    embed: discord.Embed,
    remaining_seconds: int,
) -> None:
    """Mutate the supplied (locally-constructed) embed's countdown field and
    push the edit. We deliberately do NOT read from `message.embeds[0]`: that
    round-trips the icon_url from `attachment://…` to a CDN URL, which causes
    Discord to render the original icon attachment as a standalone preview
    between embeds. Editing with the local embed keeps `attachment://…` intact
    so the icon stays bound to the embed and is hidden from the attachment list.
    """
    target_idx = -1
    target_inline = True
    for i, f in enumerate(embed.fields):
        if f.name and f.name.startswith(embeds.COUNTDOWN_FIELD_NAME):
            target_idx = i
            target_inline = bool(f.inline)
            break
    if target_idx < 0:
        return
    new_value = f"`{embeds.format_remaining(remaining_seconds)}` until timeout"
    embed.set_field_at(target_idx, name=embeds.COUNTDOWN_FIELD_NAME, value=new_value, inline=target_inline)
    try:
        await message.edit(embed=embed)
    except discord.HTTPException:
        pass


async def _wait_with_countdown(
    thread: discord.Thread,
    user: discord.abc.User,
    countdown_message: discord.Message,
    countdown_embed: discord.Embed,
    *,
    timeout: float = _DEFAULT_QUIZ_TIMEOUT,
    tick: float = _COUNTDOWN_TICK_SECONDS,
) -> discord.Message:
    """Wait for a thread message from the user; tick a countdown into the
    supplied (locally-built) embed every `tick` seconds. Cancels the ticker
    cleanly when the message arrives or the timeout fires.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    stop = asyncio.Event()

    async def _ticker() -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=tick)
                return
            except asyncio.TimeoutError:
                pass
            remaining = max(0, int(deadline - loop.time()))
            if remaining <= 0:
                return
            await _update_countdown_field(countdown_message, countdown_embed, remaining)

    ticker_task = asyncio.create_task(_ticker())
    try:
        return await _wait_for_thread_message(thread, user, timeout=timeout)
    finally:
        stop.set()
        try:
            await ticker_task
        except asyncio.CancelledError:
            pass


async def _run_quiz(
    *,
    interaction_user: discord.abc.User,
    thread: discord.Thread,
    session: dict[str, Any],
    industry: str,
    fields: list[str],
    topics: list[str],
    domain: str | None = None,
    stack: list[str] | None = None,
) -> None:
    started_at = _now_iso()
    band = session.get("band_preference", "B3")
    session_id = str(session.get("id"))
    log.info(
        "starting quiz user=%s session=%s industry=%s fields=%s topics=%s band=%s domain=%s stack=%s",
        interaction_user.id, session_id, industry, fields, topics, band, domain, stack,
    )

    fields_str = ", ".join(f"`{f}`" for f in fields) if fields else "_all 8_"
    topics_str = ", ".join(f"`{t}`" for t in topics) if topics else "_unbiased_"
    domain_str = f"`{domain}`" if domain else "_unscoped_"
    stack_str = ", ".join(f"`{s}`" for s in (stack or [])) if stack else "_unscoped_"
    intro_embed, intro_files = embeds.build(
        title="Generating questions",
        description="One LLM call · 5 scenario questions tuned to band, fields, domain, and stack.",
        fields=[
            ("Industry", f"`{industry}`", True),
            ("Band", f"`{band}`", True),
            ("Per-Q timeout", f"`{int(_DEFAULT_QUIZ_TIMEOUT // 60)}m`", True),
            ("Session", f"`{session.get('name', '?')}`", True),
            ("Domain", domain_str, True),
            ("Stack", stack_str, True),
            ("Fields", fields_str, False),
            ("Topics bias", topics_str, False),
        ],
        icon=embeds.ICON_NAMES["knowledgeharden"],
        color=embeds.BLUE_PRIMARY,
    )
    await thread.send(embed=intro_embed, files=intro_files)

    try:
        gen = await asyncio.to_thread(
            generate.generate,
            industry=industry,
            fields=fields or None,
            topics=topics or None,
            answerer_band=band,
            domain=domain,
            stack=stack,
            context_notes=None,
        )
    except generate.GenerationError as e:
        embed, files = embeds.error_embed(f"Generation failed: {e}", icon=embeds.ICON_NAMES["error"])
        await thread.send(embed=embed, files=files)
        return

    parse.questionbank(str(thread.id), gen)
    parse.apply_meta_updates(gen.get("meta_updates") or {})
    questions = parse.segment(gen)
    completed_questions: list[dict[str, Any]] = []
    model_gen = llm.get_model("generate")
    model_ref = llm.get_model("refine")

    for i, q in enumerate(questions, start=1):
        q_embed, q_files = embeds.question_embed(i, q, timeout_seconds=int(_DEFAULT_QUIZ_TIMEOUT))
        question_msg = await thread.send(embed=q_embed, files=q_files)
        try:
            answer_msg = await _wait_with_countdown(thread, interaction_user, question_msg, q_embed)
        except asyncio.TimeoutError:
            embed, files = embeds.error_embed("Timed out waiting for an answer. Run aborted.", icon=embeds.ICON_NAMES["knowledgeharden"])
            await thread.send(embed=embed, files=files)
            return
        response_text = answer_msg.content or ""

        question_record = {
            "field": q.get("field"),
            "topics": q.get("topics", []),
            "question": q.get("question", ""),
            "response": response_text,
        }
        try:
            refine_obj = await asyncio.to_thread(
                generate.refine,
                question_id=i,
                question_record=question_record,
                answerer_band=band,
                industry=industry,
            )
        except Exception as e:  # safety net — refine() already has its own fallback
            log.exception("refine() raised: %s", e)
            refine_obj = generate._deterministic_fallback(i, response_text)

        refine_response_text = ""
        if refine_obj.get("form") == "skip":
            sk_embed, sk_files = embeds.skip_embed(i)
            await thread.send(embed=sk_embed, files=sk_files)
        else:
            r_embed, r_files = embeds.refinement_embed(
                i,
                refine_obj.get("refine") or "",
                timeout_seconds=int(_DEFAULT_QUIZ_TIMEOUT),
            )
            refine_msg_sent = await thread.send(embed=r_embed, files=r_files)
            try:
                refine_msg = await _wait_with_countdown(thread, interaction_user, refine_msg_sent, r_embed)
                refine_response_text = refine_msg.content or ""
            except asyncio.TimeoutError:
                embed, files = embeds.error_embed("Timed out waiting for the refinement reply. Run aborted.", icon=embeds.ICON_NAMES["knowledgeharden"])
                await thread.send(embed=embed, files=files)
                return

        completed_questions.append({
            f"question_{i}": {
                "field": q.get("field"),
                "sfia_skills": q.get("sfia_skills", []),
                "topics": q.get("topics", []),
                "question": q.get("question", ""),
                "response": response_text,
                "refine": refine_obj.get("refine"),
                "refine_response": refine_response_text,
                "refine_form": refine_obj.get("form"),
                "refine_ambiguity_target": refine_obj.get("ambiguity_target", ""),
                "bands": [],
                "literature": [],
            }
        })

    ended_at = _now_iso()
    run_id = parse.persist_run(
        user_id=str(interaction_user.id),
        session_id=session_id,
        industry=industry,
        band=band,
        domain=domain,
        stack=stack,
        fields_invoked=fields,
        topics_invoked=topics,
        model_called=model_gen,
        model_refine=model_ref,
        started_at=started_at,
        ended_at=ended_at,
        practical_exercises=gen.get("practical_exercises", []),
        generation_metadata=gen.get("generation_metadata", {}),
        questions=completed_questions,
    )
    parse.clear_bank(str(thread.id))

    # Aggregate fields/topics actually covered (from the generated question metadata).
    fields_covered: list[str] = []
    topics_covered: list[str] = []
    seen_f: set[str] = set()
    seen_t: set[str] = set()
    for wrap in completed_questions:
        for _, qrec in wrap.items():
            f = qrec.get("field")
            if isinstance(f, str) and f not in seen_f:
                seen_f.add(f)
                fields_covered.append(f)
            for t in qrec.get("topics", []) or []:
                if t not in seen_t:
                    seen_t.add(t)
                    topics_covered.append(t)

    duration = parse.humanize_duration(started_at, ended_at)

    grading: dict[str, Any] | None = None
    graded_run: dict[str, Any] | None = None
    if parse.grader_available(industry):
        grading_embed, grading_files = embeds.info_embed(
            "Grading in progress",
            "Scoring your responses against **all five bands** and surfacing 2 pieces of literature per question…",
            icon=embeds.ICON_NAMES["grading"],
        )
        await thread.send(embed=grading_embed, files=grading_files)
        # Build a freshly-persisted run snapshot for the grader.
        active_session = parse.find_active_session_by_id(str(interaction_user.id), session_id) or {}
        current_run = next((r for r in active_session.get("runs", []) if str(r.get("id")) == str(run_id)), None)
        try:
            grading = await asyncio.to_thread(
                generate.grade,
                industry=industry,
                answerer_band=band,
                current_run=current_run or {},
                entry_state=None,
                comparison_points=None,
            )
            parse.apply_grading(str(interaction_user.id), session_id, run_id, grading)
            parse.apply_meta_updates(grading.get("meta_updates") or {})
            updated_session = parse.find_active_session_by_id(str(interaction_user.id), session_id)
            if updated_session:
                graded_run = next(
                    (r for r in updated_session.get("runs", []) if str(r.get("id")) == str(run_id)),
                    None,
                )
        except generate.GradingError as e:
            log.warning("grading failed for user=%s run=%s: %s", interaction_user.id, run_id, e)
            grading = None
            graded_run = None
    else:
        log.info("grader template unavailable for industry=%s; skipping grading", industry)

    done_embeds, done_files = embeds.run_complete_embeds(
        run_id=run_id,
        session_id=session["id"],
        durations=duration,
        exercises=gen.get("practical_exercises", []),
        industry=industry,
        band=band,
        session_name=session.get("name", "—"),
        domain=domain,
        stack=stack,
        fields_covered=fields_covered,
        topics_covered=topics_covered,
        grading=grading,
        graded_run=graded_run,
    )
    await thread.send(embeds=done_embeds, files=done_files)


@tree.command(name="knowledgeharden", description="Run a 5-question knowledge hardening quiz in your current session.")
@app_commands.describe(
    industry="Industry template directory under templates/ (default: swe).",
    fields="Comma-separated field slugs (e.g. backend,sre). Default: all 8.",
    topics="Comma-separated topic slugs to bias toward. Default: unbiased.",
    domain="Business domain to frame scenarios in (e.g. fintech, saas, healthcare, research, gaming).",
    stack="Comma-separated tech stack (e.g. python,django,postgres,react,vercel) — tunes concrete tooling in scenarios.",
)
async def knowledgeharden(
    interaction: discord.Interaction,
    industry: str | None = None,
    fields: str | None = None,
    topics: str | None = None,
    domain: str | None = None,
    stack: str | None = None,
):
    user_id = str(interaction.user.id)
    session = parse.find_active_session(user_id)
    if not session:
        embed, files = embeds.error_embed(
            "No current session. Open one with `/sessionbegin name:<unique>` or `/sessionswitch name:<existing>`.",
            icon=embeds.ICON_NAMES["error"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
        return

    session_defaults = session.get("quiz_defaults") or {}

    industries = generate.list_industries()
    industry_value = industry or session_defaults.get("industry") or generate.DEFAULT_INDUSTRY
    if industry_value not in industries:
        valid = ", ".join(f"`{i}`" for i in industries) or "(none — add a directory under templates/)"
        embed, files = embeds.error_embed(
            f"Unknown industry `{industry_value}`. Valid: {valid}.",
            icon=embeds.ICON_NAMES["error"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
        return

    fields_list = _split_csv(fields) or list(session_defaults.get("fields") or [])
    topics_list = _split_csv(topics) or list(session_defaults.get("topics") or [])
    stack_list = _split_csv(stack) or list(session_defaults.get("stack") or [])
    domain_value = (domain or "").strip() or session_defaults.get("domain") or None
    meta = parse.read_meta()
    error = _validate_args_against_meta(fields_list, topics_list, meta)
    if error:
        embed, files = embeds.error_embed(error, icon=embeds.ICON_NAMES["error"])
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
        return

    channel = interaction.channel
    if channel is None or not hasattr(channel, "create_thread"):
        embed, files = embeds.error_embed("This command must be run in a text channel.", icon=embeds.ICON_NAMES["error"])
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    session_label = session.get("name") or session["id"]
    thread = await channel.create_thread(
        name=f"Knowledge Harden — {interaction.user.display_name} — session {session_label}",
        type=discord.ChannelType.public_thread,
        auto_archive_duration=60,
    )
    ack_fields = [
        ("Industry", f"`{industry_value}`", True),
        ("Session", f"`{session_label}`", True),
        ("Band", f"`{session.get('band_preference', 'B3')}`", True),
    ]
    if fields_list:
        ack_fields.append(("Fields", ", ".join(f"`{f}`" for f in fields_list), True))
    if topics_list:
        ack_fields.append(("Topics", ", ".join(f"`{t}`" for t in topics_list), True))
    if domain_value:
        ack_fields.append(("Domain", f"`{domain_value}`", True))
    if stack_list:
        ack_fields.append(("Stack", ", ".join(f"`{s}`" for s in stack_list), True))
    ack_embed, ack_files = embeds.build(
        title="Quiz starting",
        description=f"Open {thread.mention} to answer.",
        fields=ack_fields,
        icon=embeds.ICON_NAMES["knowledgeharden"],
    )
    await interaction.followup.send(embed=ack_embed, files=ack_files, ephemeral=True)

    await _run_quiz(
        interaction_user=interaction.user,
        thread=thread,
        session=session,
        industry=industry_value,
        fields=fields_list,
        topics=topics_list,
        domain=domain_value,
        stack=stack_list or None,
    )


@knowledgeharden.autocomplete("industry")
async def _industry_autocomplete(interaction: discord.Interaction, current: str):
    current_low = (current or "").lower()
    return [
        app_commands.Choice(name=i, value=i)
        for i in generate.list_industries()
        if current_low in i.lower()
    ][:25]


# --- /help -----------------------------------------------------------------


@tree.command(name="help", description="List the bot's slash commands, grouped by category.")
async def help_cmd(interaction: discord.Interaction):
    categories: list[tuple[str, str, str, list[tuple[str, str]]]] = [
        (
            "Session management",
            "play",
            "Sessions are named, multi-active. Use `/sessionswitch` to flip between them.",
            [
                ("/sessionbegin name:<unique> [band] [industry] [fields] [topics] [domain] [stack]", "Open a new named session (band default B3). Optional scope args become defaults inherited by `/knowledgeharden` runs in this session."),
                ("/sessionend [name]", "Close the current session, or the named one. Emits a deduped reading list."),
                ("/sessionswitch name:<name>", "Set the current pointer to another active session."),
                ("/sessionlist active", "List your active sessions; current is marked."),
                ("/sessionlist closed", "List your closed (archived) sessions."),
                ("/sessionrestore id:<archive-id> name:<unique>", "Bring a closed session back to active under a new name."),
            ],
        ),
        (
            "Knowledge hardening",
            "target",
            "Tunes the quiz to your band, fields, business domain, and tech stack.",
            [
                (
                    "/knowledgeharden [industry] [fields] [topics] [domain] [stack]",
                    "Run a 5-question quiz in your current session. "
                    "`domain` (fintech, saas, healthcare, …) frames scenarios; "
                    "`stack` (python,django,react,…) tunes concrete tooling. "
                    "Grading runs at the end with 2 pieces of literature per question.",
                ),
            ],
        ),
        (
            "Stats",
            "chart-column",
            "All scopes default to the current active session.",
            [
                ("/stats runcount [n]", "Run-scoped stats. n: null/-1=whole session, 1=last run, N=last N."),
                ("/stats session [n]", "Same scope semantic, framed as session."),
                ("/stats timeline range:7d|30d|90d|all", "Stats over a recent time range."),
            ],
        ),
        (
            "Analyze",
            "trending-up",
            "Same `n` semantic as /stats.",
            [
                ("/analyze trends [n]", "Activity trends across runs."),
                ("/analyze gaps [n]", "Untouched fields and topics."),
                ("/analyze bias [n]", "Over-indexed fields relative to uniform coverage."),
            ],
        ),
        (
            "Reference",
            "book-open",
            "Look up the rubric or the field/topic graph.",
            [
                ("/rubric [field] [topics]", "Framework citations (Dreyfus / SWECOM / SFIA) and SFIA scope."),
                ("/directory [industry] [field]", "Industries → fields → topics directory."),
            ],
        ),
        (
            "Housekeeping",
            "trash-2",
            "Cleanup, re-grading, reminders, and this help message.",
            [
                ("/sweep [mode]", "Sweep abandoned runs, re-grade failed gradings, and heal the meta.json catalog (default: all)."),
                ("/transcript [run]", "Fetch the grading transcript for a run in the current session (default: latest)."),
                ("/schedule add|list|remove", "Recurring DM reminders to take a quiz."),
                ("/help", "This message."),
            ],
        ),
    ]

    all_embeds: list[discord.Embed] = []
    all_files: list[discord.File] = []
    for title, icon_name, subtitle, cmd_pairs in categories:
        fields_listed = [(name, desc, False) for name, desc in cmd_pairs]
        embed, files = embeds.build(
            title=title,
            description=subtitle,
            fields=fields_listed,
            icon=icon_name,
            color=embeds.BLUE_PRIMARY,
            footer=None,  # only the last embed needs the footer
        )
        all_embeds.append(embed)
        all_files.extend(files)
    # Restore the standard footer on the final embed.
    if all_embeds:
        all_embeds[-1].set_footer(text=embeds.DEFAULT_FOOTER)

    await interaction.response.send_message(embeds=all_embeds, files=all_files, ephemeral=True)


# --- /rubric ---------------------------------------------------------------


RUBRIC_FRAMEWORKS = [
    (
        "Dreyfus Model",
        "Stuart E. Dreyfus & Hubert L. Dreyfus, *A Five-Stage Model of the Mental Activities Involved in Directed Skill Acquisition*, U.C. Berkeley ORC, 1980. Revised: Dreyfus & Rousse, *Revisiting the Six Stages of Skill Acquisition*, 2021.",
    ),
    (
        "IEEE SWECOM",
        "IEEE Computer Society, *Software Engineering Competency Model (SWECOM)*, 2014. Aligned with SWEBOK v3.0 (ISO/IEC TR 19759:2015).",
    ),
    (
        "SFIA v9",
        "SFIA Foundation, *SFIA 9*, October 2024. Adopted by organisations across 200+ countries.",
    ),
]


@tree.command(name="rubric", description="Framework citations and per-field SFIA scope.")
@app_commands.describe(field="Field slug (optional).", topics="Comma-separated topic slugs (optional).")
async def rubric(interaction: discord.Interaction, field: str | None = None, topics: str | None = None):
    fields_listed: list[tuple[str, str, bool]] = [(name, body, False) for name, body in RUBRIC_FRAMEWORKS]
    description = "Citations behind the 5-band grading methodology."

    if field:
        if field not in parse.CANONICAL_FIELDS:
            embed, files = embeds.error_embed(
                f"Unknown field `{field}`. Valid: {', '.join(parse.CANONICAL_FIELDS.keys())}.",
                icon=embeds.ICON_NAMES["rubric"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        skills = parse.CANONICAL_FIELDS[field]["sfia_skills"]
        fields_listed.append((f"SFIA scope · {field}", ", ".join(skills), False))
        topics_list = _split_csv(topics)
        if topics_list:
            tag_str = " ".join(f"`{t}`" for t in topics_list)
            fields_listed.append(("Topics", tag_str, False))

    embed, files = embeds.build(
        title="Rubric & frameworks",
        description=description,
        fields=fields_listed,
        icon=embeds.ICON_NAMES["rubric"],
    )
    await interaction.response.send_message(embed=embed, files=files, ephemeral=True)


# --- /directory ------------------------------------------------------------


@tree.command(name="directory", description="Industries → fields → topics. No args lists industries.")
@app_commands.describe(
    industry="Industry slug; pass it to list fields under that industry.",
    field="Field slug; with an industry, lists topics under that field.",
)
async def directory(
    interaction: discord.Interaction,
    industry: str | None = None,
    field: str | None = None,
):
    industries = generate.list_industries()
    meta = parse.read_meta()
    fields_dict = meta.get("fields", {})

    # No args → list industries.
    if not industry:
        if field:
            embed, files = embeds.error_embed(
                "`field` requires an `industry` argument.",
                icon=embeds.ICON_NAMES["directory"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        if not industries:
            embed, files = embeds.error_embed(
                "No industries found under `templates/`.",
                icon=embeds.ICON_NAMES["directory"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        rows: list[tuple[str, str, bool]] = []
        for ind in industries:
            field_count = len(parse.CANONICAL_FIELDS)
            topic_count = sum(len(fields_dict.get(s, {}).get("topics", []) or []) for s in parse.CANONICAL_FIELDS)
            rows.append((ind, f"`{ind}` · {field_count} field(s) · {topic_count} topic(s)", False))
        embed, files = embeds.build(
            title="Industry directory",
            description="Industries are template namespaces under `templates/`.",
            fields=rows,
            icon=embeds.ICON_NAMES["directory"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
        return

    # Validate industry.
    if industry not in industries:
        valid = ", ".join(f"`{i}`" for i in industries) or "(none)"
        embed, files = embeds.error_embed(
            f"Unknown industry `{industry}`. Valid: {valid}.",
            icon=embeds.ICON_NAMES["directory"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
        return

    # `industry` only → list fields under that industry (topic counts come from the shared meta.json).
    if not field:
        rows = []
        for slug, meta_entry in parse.CANONICAL_FIELDS.items():
            topic_count = len(fields_dict.get(slug, {}).get("topics", []) or [])
            rows.append((meta_entry["name"], f"`{slug}` · {topic_count} topic(s)\n{meta_entry['description']}", False))
        embed, files = embeds.build(
            title=f"Fields · {industry}",
            description="The 8 canonical engineering fields. Pass `field` to list topics.",
            fields=rows,
            icon=embeds.ICON_NAMES["directory"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
        return

    # `industry` + `field` → list topics under that field.
    if field not in parse.CANONICAL_FIELDS:
        valid = ", ".join(f"`{k}`" for k in parse.CANONICAL_FIELDS.keys())
        embed, files = embeds.error_embed(
            f"Unknown field `{field}`. Valid: {valid}.",
            icon=embeds.ICON_NAMES["directory"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
        return
    topics = fields_dict.get(field, {}).get("topics", []) or []
    body = "\n".join(f"• `{t}`" for t in topics) if topics else "_No topics yet — they grow as questions are generated._"
    embed, files = embeds.build(
        title=f"Topics · {industry} / {field}",
        description=parse.CANONICAL_FIELDS[field]["description"],
        fields=[("Topics", body, False)],
        icon=embeds.ICON_NAMES["directory"],
    )
    await interaction.response.send_message(embed=embed, files=files, ephemeral=True)


@directory.autocomplete("industry")
async def _directory_industry_autocomplete(interaction: discord.Interaction, current: str):
    current_low = (current or "").lower()
    return [
        app_commands.Choice(name=i, value=i)
        for i in generate.list_industries()
        if current_low in i.lower()
    ][:25]


@directory.autocomplete("field")
async def _directory_field_autocomplete(interaction: discord.Interaction, current: str):
    current_low = (current or "").lower()
    return [
        app_commands.Choice(name=slug, value=slug)
        for slug in parse.CANONICAL_FIELDS
        if current_low in slug.lower()
    ][:25]


# --- /schedule -------------------------------------------------------------


schedule_group = app_commands.Group(name="schedule", description="Recurring reminders to take a quiz.")


@schedule_group.command(name="add", description="Add a recurring reminder.")
@app_commands.describe(cadence="How often to fire.", time="Local time as HH:MM (24h UTC).")
@app_commands.choices(cadence=[
    app_commands.Choice(name="Daily", value="daily"),
    app_commands.Choice(name="Every other day", value="every-other-day"),
    app_commands.Choice(name="Weekly (Mondays)", value="weekly"),
])
async def schedule_add(
    interaction: discord.Interaction,
    cadence: app_commands.Choice[str],
    time: str,
):
    confirmed = await confirm.ask_confirm(
        interaction,
        action="Add schedule",
        detail=f"Create a `{cadence.name}` reminder at **{time} UTC**.",
        icon=embeds.ICON_NAMES["schedule"],
    )
    if not confirmed:
        embed, files = embeds.info_embed("Cancelled", "No schedule added.", icon=embeds.ICON_NAMES["schedule"])
        await interaction.followup.send(embed=embed, files=files, ephemeral=True)
        return
    try:
        job_id = scheduler.add(interaction.user.id, cadence.value, time)
    except ValueError as e:
        embed, files = embeds.error_embed(str(e), icon=embeds.ICON_NAMES["schedule"])
        await interaction.followup.send(embed=embed, files=files, ephemeral=True)
        return
    embed, files = embeds.info_embed(
        "Schedule added",
        f"Job `{job_id}` will fire on cadence **{cadence.name}** at **{time} UTC**.",
        icon=embeds.ICON_NAMES["schedule"],
    )
    await interaction.followup.send(embed=embed, files=files, ephemeral=True)


@schedule_group.command(name="list", description="List your active schedules.")
async def schedule_list(interaction: discord.Interaction):
    rows = scheduler.list_for_user(interaction.user.id)
    if not rows:
        embed, files = embeds.info_embed("No schedules", "Use `/schedule add` to create one.", icon=embeds.ICON_NAMES["schedule"])
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
        return
    fields_listed: list[tuple[str, str, bool]] = []
    for r in rows:
        fields_listed.append((f"Job `{r['id']}`", f"Next: `{r['next_run'] or '—'}`\nTrigger: `{r['trigger']}`", False))
    embed, files = embeds.build(
        title="Schedules",
        description=f"{len(rows)} active job(s).",
        fields=fields_listed,
        icon=embeds.ICON_NAMES["schedule"],
    )
    await interaction.response.send_message(embed=embed, files=files, ephemeral=True)


@schedule_group.command(name="remove", description="Remove a schedule by id.")
@app_commands.describe(id="Job id from /schedule list.")
async def schedule_remove(interaction: discord.Interaction, id: str):
    confirmed = await confirm.ask_confirm(
        interaction,
        action="Remove schedule",
        detail=f"Delete job `{id}`.",
        icon=embeds.ICON_NAMES["schedule"],
    )
    if not confirmed:
        embed, files = embeds.info_embed("Cancelled", "Schedule not removed.", icon=embeds.ICON_NAMES["schedule"])
        await interaction.followup.send(embed=embed, files=files, ephemeral=True)
        return
    ok = scheduler.remove(interaction.user.id, id)
    if not ok:
        embed, files = embeds.error_embed(f"Job `{id}` not found.", icon=embeds.ICON_NAMES["schedule"])
        await interaction.followup.send(embed=embed, files=files, ephemeral=True)
        return
    embed, files = embeds.info_embed("Schedule removed", f"Job `{id}` deleted.", icon=embeds.ICON_NAMES["schedule"])
    await interaction.followup.send(embed=embed, files=files, ephemeral=True)


tree.add_command(schedule_group)


# --- /sweep ---------------------------------------------------------------


_SWEEP_MODES = [
    app_commands.Choice(name="All — cleanup + regrade + catalog (recommended)", value="all"),
    app_commands.Choice(name="Cleanup only — drop runs with no answers", value="cleanup"),
    app_commands.Choice(name="Regrade only — re-run grading on failed runs", value="regrade"),
    app_commands.Choice(name="Catalog only — heal meta.json from your run history", value="catalog"),
]


async def _regrade_one(user_id: str, session_id: str, run: dict[str, Any], session: dict[str, Any]) -> tuple[bool, str]:
    run_industry = (run.get("industry") or "swe").lower()
    run_band = run.get("band") or session.get("band_preference", "B3")
    if not parse.grader_available(run_industry):
        return False, f"grader template missing for industry `{run_industry}`"
    try:
        grading = await asyncio.to_thread(
            generate.grade,
            industry=run_industry,
            answerer_band=run_band,
            current_run=run,
        )
    except generate.GradingError as e:
        return False, str(e)
    parse.apply_grading(user_id, session_id, str(run["id"]), grading)
    parse.apply_meta_updates(grading.get("meta_updates") or {})
    return True, ""


@tree.command(name="sweep", description="Sweep abandoned runs, re-grade failed gradings, and heal the meta.json catalog.")
@app_commands.describe(mode="cleanup, regrade, catalog, or all. Default: all.")
@app_commands.choices(mode=_SWEEP_MODES)
async def sweep(interaction: discord.Interaction, mode: app_commands.Choice[str] | None = None):
    user_id = str(interaction.user.id)
    active = parse.find_active_session(user_id)
    if active is None:
        embed, files = embeds.error_embed(
            "No current session. Open one with `/sessionbegin` first or `/sessionswitch` to one of your active sessions.",
            icon=embeds.ICON_NAMES["error"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
        return
    session_id = str(active["id"])

    chosen = mode.value if mode is not None else "all"
    do_cleanup = chosen in ("cleanup", "all")
    do_regrade = chosen in ("regrade", "all")
    do_catalog = chosen in ("catalog", "all")

    await interaction.response.defer(ephemeral=True, thinking=True)

    cleaned_ids: list[str] = []
    if do_cleanup:
        cleaned_ids = parse.cleanup_abandoned_runs(user_id, session_id=session_id)

    regraded_ids: list[str] = []
    failed_regrades: list[tuple[str, str]] = []
    skipped_count = 0
    if do_regrade:
        active_after = parse.find_active_session_by_id(user_id, session_id) or {}
        targets = parse.runs_needing_grading(user_id, session_id=session_id)
        skipped_count = len([
            r for r in (active_after.get("runs", []) or [])
            if r.get("status") == "complete" and r.get("aggregated_score") is None
            and not parse._run_has_any_response(r)
        ])
        for r in targets:
            ok, err = await _regrade_one(user_id, session_id, r, active_after)
            if ok:
                regraded_ids.append(str(r.get("id", "?")))
            else:
                failed_regrades.append((str(r.get("id", "?")), err))

    catalog_summary: dict[str, Any] | None = None
    if do_catalog:
        catalog_summary = await asyncio.to_thread(parse.heal_meta_from_user_runs, user_id)

    fields_listed: list[tuple[str, str, bool]] = []

    if do_cleanup:
        if cleaned_ids:
            body = f"Removed **{len(cleaned_ids)}** run(s): {', '.join(f'`#{i}`' for i in cleaned_ids)}"
        else:
            body = "_No abandoned runs found._"
        fields_listed.append(("🧹 Cleanup", body, False))

    if do_regrade:
        body_lines: list[str] = []
        if regraded_ids:
            body_lines.append(f"✅ Re-graded **{len(regraded_ids)}** run(s): {', '.join(f'`#{i}`' for i in regraded_ids)}")
        if failed_regrades:
            body_lines.append(
                "⚠️ Still failing:\n"
                + "\n".join(f"  • `#{rid}` — {err}" for rid, err in failed_regrades)
            )
        if skipped_count and do_cleanup is False:
            body_lines.append(f"ℹ️ Skipped {skipped_count} ungraded run(s) with no responses (run `cleanup` to drop them).")
        if not body_lines:
            body_lines.append("_No runs needed re-grading._")
        fields_listed.append(("♻️ Regrade", "\n".join(body_lines), False))

    if do_catalog and catalog_summary is not None:
        runs_n = catalog_summary["runs_processed"]
        fields_added = catalog_summary["fields_added"]
        topics_added = catalog_summary["topics_added_total"]
        if runs_n == 0:
            body = "_No runs found to heal from._"
        elif not fields_added and topics_added == 0:
            body = f"Walked **{runs_n}** run(s); meta.json already in sync."
        else:
            parts = [f"Walked **{runs_n}** run(s)."]
            if fields_added:
                parts.append(f"Added field(s): {', '.join(f'`{f}`' for f in fields_added)}.")
            if topics_added:
                parts.append(f"Added **{topics_added}** new topic(s) across canonical fields.")
            body = " ".join(parts)
        fields_listed.append(("📚 Catalog", body, False))

    color = embeds.OK_GREEN if not failed_regrades else embeds.WARN_AMBER
    icon = embeds.ICON_NAMES["regrade"] if do_regrade and not do_cleanup and not do_catalog else embeds.ICON_NAMES["sweep"]
    embed, files = embeds.build(
        title="Housekeeping complete",
        description=f"Mode: **{chosen}** · session **`{active.get('name', '?')}`** (id `{active.get('id', '?')}`).",
        fields=fields_listed,
        icon=icon,
        color=color,
    )
    await interaction.followup.send(embed=embed, files=files, ephemeral=True)


# --- scheduler fire callback ----------------------------------------------


async def _on_schedule_fire(user_id: int, job_id: str) -> None:
    user = bot.get_user(user_id)
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except discord.HTTPException:
            log.warning("scheduler fire: cannot resolve user %s", user_id)
            return
    embed, files = embeds.info_embed(
        "Time for a knowledge harden",
        "Open a session with `/sessionbegin`, then run `/knowledgeharden` to begin.",
        icon=embeds.ICON_NAMES["knowledgeharden"],
    )
    try:
        await user.send(embed=embed, files=files)
    except discord.Forbidden:
        log.warning("user %s has DMs disabled; cannot deliver schedule fire", user_id)


# --- lifecycle -------------------------------------------------------------


@bot.event
async def on_ready():
    log.info("logged in as %s (%s)", bot.user, bot.user.id if bot.user else "?")
    parse.ensure_runtime_dirs()
    parse.seed_meta_if_empty()
    industries = generate.list_industries()
    log.info("industries available: %s", industries or "(none)")
    for industry in industries:
        if not parse.grader_available(industry):
            log.warning("templates/%s/grader.md is empty — grading unavailable for this industry.", industry)
    scheduler.start(asyncio.get_running_loop(), _on_schedule_fire)

    # Slash command sync. Global syncs propagate over up to ~1 hour, which
    # makes development frustrating when a parameter list changes. If
    # DEV_GUILD_ID is set, we copy the global tree into that guild and sync
    # there too — guild-scoped commands appear immediately.
    dev_guild_id = os.environ.get("DEV_GUILD_ID", "").strip()
    try:
        synced_global = await tree.sync()
        log.info(
            "synced %d global slash commands: %s",
            len(synced_global),
            ", ".join(sorted(c.name for c in synced_global)),
        )
        if dev_guild_id:
            try:
                guild = discord.Object(id=int(dev_guild_id))
            except ValueError:
                log.warning("DEV_GUILD_ID=%r is not a valid integer; skipping guild sync", dev_guild_id)
            else:
                tree.copy_global_to(guild=guild)
                synced_guild = await tree.sync(guild=guild)
                log.info(
                    "synced %d slash commands to guild %s (instant): %s",
                    len(synced_guild),
                    dev_guild_id,
                    ", ".join(sorted(c.name for c in synced_guild)),
                )
    except discord.HTTPException as e:
        log.error("command sync failed: %s", e)


@bot.event
async def on_disconnect():
    log.info("bot disconnected")


def main() -> None:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN is not set.")
    parse.ensure_runtime_dirs()
    parse.seed_meta_if_empty()
    bot.run(token)


if __name__ == "__main__":
    main()
