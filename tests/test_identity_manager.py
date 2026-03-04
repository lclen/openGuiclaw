"""
Property-based tests for IdentityManager.

# Feature: self-evolution-refactor

Validates: Requirements 2.2, 2.3, 2.4, 2.5, 6.1, 6.2, 6.4, 6.5
"""

import json
import re
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.identity_manager import IdentityManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_manager(tmp_path: Path) -> IdentityManager:
    return IdentityManager(data_dir=str(tmp_path))


def make_profile_json(tmp_path: Path, objective: dict, subjective: dict) -> Path:
    p = tmp_path / "user_profile.json"
    p.write_text(
        json.dumps({"objective_memory": objective, "subjective_memory": subjective},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    return p


def make_habits_md(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "interaction_habits.md"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Property 3: 迁移数据完整性
# For any profile dict, USER.md/HABITS.md must contain all key-value pairs.
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    objective=st.dictionaries(
        st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_")),
        st.text(min_size=0, max_size=50),
        min_size=0,
        max_size=5,
    ),
    subjective=st.dictionaries(
        st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_")),
        st.text(min_size=0, max_size=50),
        min_size=0,
        max_size=5,
    ),
    habits_content=st.text(min_size=0, max_size=200),
)
def test_property3_migration_data_integrity(objective, subjective, habits_content):
    """
    # Feature: self-evolution-refactor, Property 3: 迁移数据完整性
    After migration, USER.md contains all objective keys/values,
    HABITS.md contains all subjective keys/values and habits content.
    Validates: Requirements 2.2, 2.3
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        profile_path = make_profile_json(tmp_path, objective, subjective)
        habits_path = make_habits_md(tmp_path, habits_content)

        mgr = make_manager(tmp_path)
        mgr.migrate_from_legacy(str(profile_path), str(habits_path))

        user_text = (tmp_path / "identity" / "USER.md").read_text(encoding="utf-8")
        habits_text = (tmp_path / "identity" / "HABITS.md").read_text(encoding="utf-8")

        # All objective keys and values must appear in USER.md
        for key, value in objective.items():
            norm_value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
            assert key in user_text, f"Objective key '{key}' missing from USER.md"
            assert norm_value in user_text, f"Objective value '{value}' missing from USER.md"

        # All subjective keys and values must appear in HABITS.md
        for key, value in subjective.items():
            norm_value = value.replace("\r\n", "\n").replace("\r", "\n")
            assert key in habits_text, f"Subjective key '{key}' missing from HABITS.md"
            assert norm_value in habits_text, f"Subjective value '{value}' missing from HABITS.md"

        # habits_content must appear in HABITS.md (if non-empty)
        normalized_habits = habits_content.replace("\r\n", "\n").replace("\r", "\n")
        if normalized_habits.strip():
            assert normalized_habits.strip() in habits_text


# ---------------------------------------------------------------------------
# Property 4: 迁移备份保留
# After migration, original files are renamed to .bak with identical content.
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    objective=st.dictionaries(
        st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("Lu", "Ll"), whitelist_characters="_")),
        st.text(min_size=0, max_size=30),
        min_size=0,
        max_size=3,
    ),
    habits_content=st.text(min_size=0, max_size=100),
)
def test_property4_migration_backup_preserved(objective, habits_content):
    """
    # Feature: self-evolution-refactor, Property 4: 迁移备份保留
    After migration, .bak files exist and their content matches the originals.
    Validates: Requirements 2.4
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        profile_path = make_profile_json(tmp_path, objective, {})
        habits_path = make_habits_md(tmp_path, habits_content)

        original_profile = profile_path.read_text(encoding="utf-8")
        original_habits = habits_path.read_text(encoding="utf-8")

        mgr = make_manager(tmp_path)
        mgr.migrate_from_legacy(str(profile_path), str(habits_path))

        profile_bak = tmp_path / "user_profile.json.bak"
        habits_bak = tmp_path / "interaction_habits.md.bak"

        assert profile_bak.exists(), ".bak file for user_profile.json must exist"
        assert habits_bak.exists(), ".bak file for interaction_habits.md must exist"

        assert profile_bak.read_text(encoding="utf-8") == original_profile
        assert habits_bak.read_text(encoding="utf-8") == original_habits


# ---------------------------------------------------------------------------
# Property 5: build_prompt 从 identity 读取
# build_prompt() must include content from USER.md and HABITS.md.
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    user_key=st.text(min_size=1, max_size=15, alphabet=st.characters(whitelist_categories=("Lu", "Ll"), whitelist_characters="_")),
    user_value=st.text(min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=" ")),
    habit_content=st.text(min_size=1, max_size=100, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=" \n")),
)
def test_property5_build_prompt_reads_from_identity(user_key, user_value, habit_content):
    """
    # Feature: self-evolution-refactor, Property 5: build_prompt 从 identity 读取
    build_prompt() returns a string containing USER.md and HABITS.md content.
    Validates: Requirements 2.5, 6.3
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mgr = make_manager(tmp_path)

        mgr.update_user(user_key, user_value)
        mgr.append_habit(habit_content)

        prompt = mgr.build_prompt()

        assert user_key in prompt, f"USER key '{user_key}' not in build_prompt()"
        assert user_value.strip() in prompt, f"USER value '{user_value}' not in build_prompt()"
        assert habit_content.strip() in prompt, "Habit content not in build_prompt()"


# ---------------------------------------------------------------------------
# Property 11: 记忆按 layer 路由
# objective updates go to USER.md; subjective updates go to HABITS.md.
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    key=st.text(min_size=1, max_size=15, alphabet=st.characters(whitelist_categories=("Lu", "Ll"), whitelist_characters="_")),
    value=st.text(min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=" ")),
    layer=st.sampled_from(["objective", "subjective"]),
)
def test_property11_memory_layer_routing(key, value, layer):
    """
    # Feature: self-evolution-refactor, Property 11: 记忆按 layer 路由
    objective layer writes to USER.md; subjective layer writes to HABITS.md.
    Validates: Requirements 6.1, 6.2, 6.4
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mgr = make_manager(tmp_path)

        if layer == "objective":
            mgr.update_user(key, value)
            user_text = (tmp_path / "identity" / "USER.md").read_text(encoding="utf-8")
            habits_text = (tmp_path / "identity" / "HABITS.md").read_text(encoding="utf-8")
            assert key in user_text, f"Objective key '{key}' should be in USER.md"
            assert value in user_text, f"Objective value '{value}' should be in USER.md"
            # Value should NOT appear in HABITS.md (unless it's a coincidence with default header)
            # We only check the key is not in HABITS.md as a kv pair
            assert f"**{key}**" not in habits_text, f"Objective key should not appear in HABITS.md"
        else:
            content = f"- **{key}**: {value}"
            mgr.append_habit(content)
            habits_text = (tmp_path / "identity" / "HABITS.md").read_text(encoding="utf-8")
            user_text = (tmp_path / "identity" / "USER.md").read_text(encoding="utf-8")
            assert key in habits_text, f"Subjective key '{key}' should be in HABITS.md"
            assert value in habits_text, f"Subjective value '{value}' should be in HABITS.md"
            # Should not appear in USER.md
            assert f"**{key}**" not in user_text, f"Subjective key should not appear in USER.md"


# ---------------------------------------------------------------------------
# Property 12: 时间戳格式正确
# After any write, files contain <!-- updated: YYYY-MM-DD --> timestamp.
# ---------------------------------------------------------------------------

TIMESTAMP_RE = re.compile(r"<!-- updated: \d{4}-\d{2}-\d{2}[^>]* -->")


@settings(max_examples=100)
@given(
    key=st.text(min_size=1, max_size=15, alphabet=st.characters(whitelist_categories=("Lu", "Ll"), whitelist_characters="_")),
    value=st.text(min_size=0, max_size=30),
    habit=st.text(min_size=1, max_size=50),
    memory=st.text(min_size=0, max_size=900),
)
def test_property12_timestamp_format(key, value, habit, memory):
    """
    # Feature: self-evolution-refactor, Property 12: 时间戳格式正确
    After write operations, files contain <!-- updated: YYYY-MM-DD --> timestamp.
    Validates: Requirements 6.5
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mgr = make_manager(tmp_path)

        mgr.update_user(key, value)
        mgr.append_habit(habit)
        mgr.write_memory(memory)

        user_text = (tmp_path / "identity" / "USER.md").read_text(encoding="utf-8")
        habits_text = (tmp_path / "identity" / "HABITS.md").read_text(encoding="utf-8")
        memory_text = (tmp_path / "identity" / "MEMORY.md").read_text(encoding="utf-8")

        assert TIMESTAMP_RE.search(user_text), "USER.md missing valid timestamp"
        assert TIMESTAMP_RE.search(habits_text), "HABITS.md missing valid timestamp"
        assert TIMESTAMP_RE.search(memory_text), "MEMORY.md missing valid timestamp"
