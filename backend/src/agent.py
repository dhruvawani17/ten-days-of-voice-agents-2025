"""
Day 8 – Voice Game Master (SUPER SIMPLE Voice-Only Adventure)
Drop-in replacement: much smaller world, voice-friendly, minimal choices.

Tools:
    - start_adventure(): start a fresh session and introduce the scene
    - get_scene(): return the current scene description (GM text) ending with "What do you do?"
    - player_action(action_text): accept player's spoken action, update state, advance scene
    - show_journal(): list remembered facts, simple history, choices, current scene
    - restart_adventure(): reset state and start over

This file preserves the LiveKit plumbing and plugins (murf, deepgram, silero, turn detector).
"""

import json
import logging
import os
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Annotated

from dotenv import load_dotenv
from pydantic import Field
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    function_tool,
    RunContext,
)

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

# -------------------------
# Logging
# -------------------------
logger = logging.getLogger("voice_game_master_simple")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)

load_dotenv(".env.local")

# -------------------------
# SUPER SIMPLE WORLD (drop-in replacement)
# -------------------------
WORLD = {
    "intro": {
        "title": "Forest Edge",
        "desc": (
            "You stand at the edge of a quiet forest. A narrow path leads inside. "
            "To your right, a wooden sign points ahead: 'Cave — 5 minutes'."
        ),
        "choices": {
            "enter_forest": {
                "desc": "Walk into the forest.",
                "result_scene": "forest",
            },
            "read_sign": {
                "desc": "Read the wooden sign.",
                "result_scene": "sign",
            },
        },
    },

    "sign": {
        "title": "The Signpost",
        "desc": "The sign simply says: 'Cave – 5 minutes ahead'. The forest path is the only way forward.",
        "choices": {
            "go_to_forest": {
                "desc": "Walk into the forest.",
                "result_scene": "forest",
            },
            "return": {
                "desc": "Step back from the sign.",
                "result_scene": "intro",
            },
        },
    },

    "forest": {
        "title": "Inside the Forest",
        "desc": (
            "The forest is calm. Birds chirp. The path becomes dimmer as it approaches a cave entrance."
        ),
        "choices": {
            "go_to_cave": {
                "desc": "Walk toward the cave.",
                "result_scene": "cave",
            },
            "look_around": {
                "desc": "Look around the peaceful forest.",
                "result_scene": "forest_look",
            },
            "back": {
                "desc": "Return to the edge of the forest.",
                "result_scene": "intro",
            },
        },
    },

    "forest_look": {
        "title": "A Peaceful Spot",
        "desc": (
            "Sunlight breaks through leaves. You find nothing of note — just quiet and a faint breeze."
        ),
        "choices": {
            "continue_to_cave": {
                "desc": "Continue to the cave entrance.",
                "result_scene": "cave",
            },
            "back": {
                "desc": "Return to the forest path.",
                "result_scene": "forest",
            },
        },
    },

    "cave": {
        "title": "The Cave Entrance",
        "desc": (
            "The cave is cool. A soft glow comes from deeper inside. You hear a distant drip."
        ),
        "choices": {
            "enter_cave": {
                "desc": "Go deeper into the cave.",
                "result_scene": "treasure",
            },
            "leave": {
                "desc": "Return to the forest.",
                "result_scene": "forest",
            },
        },
    },

    "treasure": {
        "title": "Treasure Chamber",
        "desc": (
            "You step into a small chamber. On a stone pedestal sits a tiny glowing chest. Inside, a single golden coin rests."
        ),
        "choices": {
            "take_coin": {
                "desc": "Take the golden coin.",
                "result_scene": "ending",
                "effects": {"add_journal": "Found a tiny golden coin."},
            },
            "leave_it": {
                "desc": "Leave the coin and go back.",
                "result_scene": "forest",
            },
        },
    },

    "ending": {
        "title": "A Happy Ending",
        "desc": (
            "You take the golden coin. A warm light fills the chamber. The small adventure is complete."
        ),
        "choices": {
            "restart": {
                "desc": "Start a new game.",
                "result_scene": "intro",
            },
        },
    },
}

# -------------------------
# Per-session Userdata (keeps it minimal)
# -------------------------
@dataclass
class Userdata:
    player_name: Optional[str] = None
    current_scene: str = "intro"
    history: List[Dict] = field(default_factory=list)
    journal: List[str] = field(default_factory=list)
    choices_made: List[str] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

# -------------------------
# Helper functions
# -------------------------
def scene_text(scene_key: str, userdata: Userdata) -> str:
    """
    Build the descriptive text for the current scene, and append choices as short hints.
    Always end with 'What do you do?' so the voice flow prompts player input.
    """
    scene = WORLD.get(scene_key)
    if not scene:
        return "You are in a featureless void. What do you do?"

    desc = f"{scene['desc']}\n\nChoices:\n"
    for cid, cmeta in scene.get("choices", {}).items():
        desc += f"- {cmeta['desc']} (say: {cid})\n"
    # GM MUST end with the action prompt
    desc += "\nWhat do you do?"
    return desc

def apply_effects(effects: dict, userdata: Userdata):
    if not effects:
        return
    if "add_journal" in effects:
        userdata.journal.append(effects["add_journal"])
    # Keep effects minimal and extendable

def summarize_scene_transition(old_scene: str, action_key: str, result_scene: str, userdata: Userdata) -> str:
    """Record the transition into history and return a short narrative the GM can use."""
    entry = {
        "from": old_scene,
        "action": action_key,
        "to": result_scene,
        "time": datetime.utcnow().isoformat() + "Z",
    }
    userdata.history.append(entry)
    userdata.choices_made.append(action_key)
    return f"You chose '{action_key}'."

# -------------------------
# Agent Tools (function_tool)
# -------------------------

@function_tool
async def start_adventure(
    ctx: RunContext[Userdata],
    player_name: Annotated[Optional[str], Field(description="Player name", default=None)] = None,
) -> str:
    """Initialize a new adventure session for the player and return the opening description."""
    userdata = ctx.userdata
    if player_name:
        userdata.player_name = player_name
    userdata.current_scene = "intro"
    userdata.history = []
    userdata.journal = []
    userdata.choices_made = []
    userdata.session_id = str(uuid.uuid4())[:8]
    userdata.started_at = datetime.utcnow().isoformat() + "Z"

    opening = (
        f"Greetings {userdata.player_name or 'traveler'}. Welcome to '{WORLD['intro']['title']}'.\n\n"
        + scene_text("intro", userdata)
    )
    # Ensure GM prompt present
    if not opening.endswith("What do you do?"):
        opening += "\nWhat do you do?"
    return opening

@function_tool
async def get_scene(
    ctx: RunContext[Userdata],
) -> str:
    """Return the current scene description (useful for 'remind me where I am')."""
    userdata = ctx.userdata
    scene_k = userdata.current_scene or "intro"
    txt = scene_text(scene_k, userdata)
    return txt

@function_tool
async def player_action(
    ctx: RunContext[Userdata],
    action: Annotated[str, Field(description="Player spoken action or the short action code (e.g., 'enter_forest' or 'walk into the forest')")],
) -> str:
    """
    Accept player's action (natural language or action key), try to resolve it to a defined choice,
    update userdata, advance to the next scene and return the GM's next description (ending with 'What do you do?').
    """
    userdata = ctx.userdata
    current = userdata.current_scene or "intro"
    scene = WORLD.get(current)
    action_text = (action or "").strip()

    # Attempt 1: match exact action key (e.g., 'enter_forest')
    chosen_key = None
    if action_text.lower() in (scene.get("choices") or {}):
        chosen_key = action_text.lower()

    # Attempt 2: fuzzy match by checking if action_text contains the choice key or some words from the choice description
    if not chosen_key:
        for cid, cmeta in (scene.get("choices") or {}).items():
            desc = cmeta.get("desc", "").lower()
            if cid in action_text.lower() or any(w in action_text.lower() for w in desc.split()[:3]):
                chosen_key = cid
                break

    # Attempt 3: fallback by keyword matching
    if not chosen_key:
        for cid, cmeta in (scene.get("choices") or {}).items():
            for keyword in cmeta.get("desc", "").lower().split():
                if keyword and keyword in action_text.lower():
                    chosen_key = cid
                    break
            if chosen_key:
                break

    if not chosen_key:
        # Can't resolve action — short clarifying reply with prompt
        resp = (
            "I didn't catch that. Try one of the listed choices or use a short phrase like 'enter forest' or 'read sign'.\n\n"
            + scene_text(current, userdata)
        )
        return resp

    # Apply the chosen choice
    choice_meta = scene["choices"].get(chosen_key)
    result_scene = choice_meta.get("result_scene", current)
    effects = choice_meta.get("effects", None)

    # Apply effects (journal, etc.)
    apply_effects(effects or {}, userdata)

    # Record transition
    _note = summarize_scene_transition(current, chosen_key, result_scene, userdata)

    # Update current scene
    userdata.current_scene = result_scene

    # Build narrative reply
    next_desc = scene_text(result_scene, userdata)

    # Persona flourish kept short for voice delivery
    persona_pre = "The Game Master replies:\n\n"
    reply = f"{persona_pre}{_note}\n\n{next_desc}"
    if not reply.endswith("What do you do?"):
        reply += "\nWhat do you do?"
    return reply

@function_tool
async def show_journal(
    ctx: RunContext[Userdata],
) -> str:
    userdata = ctx.userdata
    lines = []
    lines.append(f"Session: {userdata.session_id} | Started at: {userdata.started_at}")
    if userdata.player_name:
        lines.append(f"Player: {userdata.player_name}")
    if userdata.journal:
        lines.append("\nJournal entries:")
        for j in userdata.journal:
            lines.append(f"- {j}")
    else:
        lines.append("\nJournal is empty.")
    lines.append("\nRecent choices:")
    for h in userdata.history[-6:]:
        lines.append(f"- {h['time']} | {h['from']} -> {h['to']} via {h['action']}")
    lines.append("\nWhat do you do?")
    return "\n".join(lines)

@function_tool
async def restart_adventure(
    ctx: RunContext[Userdata],
) -> str:
    """Reset the userdata and start again."""
    userdata = ctx.userdata
    userdata.current_scene = "intro"
    userdata.history = []
    userdata.journal = []
    userdata.choices_made = []
    userdata.session_id = str(uuid.uuid4())[:8]
    userdata.started_at = datetime.utcnow().isoformat() + "Z"
    greeting = (
        "The world resets. A new day begins at the forest edge.\n\n"
        + scene_text("intro", userdata)
    )
    if not greeting.endswith("What do you do?"):
        greeting += "\nWhat do you do?"
    return greeting

# -------------------------
# The Agent (GameMasterAgent)
# -------------------------
class GameMasterAgent(Agent):
    def __init__(self):
        instructions = """
        You are 'Aurek', the Game Master for a voice-only, tiny adventure.
        Universe: Simple outdoors / cave.
        Tone: Friendly, concise, evocative — good for spoken delivery.
        Role: Describe scenes, accept short voiced actions, remember simple journal entries and recent choices,
              and always end descriptions with 'What do you do?'
        Rules:
            - Use the provided tools only.
            - Keep responses short (suitable for TTS).
            - Maintain session continuity via userdata.
        """
        super().__init__(
            instructions=instructions,
            tools=[start_adventure, get_scene, player_action, show_journal, restart_adventure],
        )

# -------------------------
# Entrypoint & Prewarm (keeps speech functionality)
# -------------------------
def prewarm(proc: JobProcess):
    # try to load VAD model and stash it on process userdata
    try:
        proc.userdata["vad"] = silero.VAD.load()
    except Exception:
        logger.warning("VAD prewarm failed; continuing without preloaded VAD.")

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    logger.info("\n" + "🎲" * 6)
    logger.info("🚀 STARTING SIMPLE VOICE GAME MASTER")

    userdata = Userdata()

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-marcus",
            style="Conversational",
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata.get("vad"),
        userdata=userdata,
    )

    # Start the agent session with the GameMasterAgent
    await session.start(
        agent=GameMasterAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )

    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
