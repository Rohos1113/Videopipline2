from unittest.mock import AsyncMock

import pytest

from app.models import Project
from app.services.action_layer.builtin_voice import pick_voice
from app.web.routers.db_browser import _execute_orchestrator_reply


def test_pick_voice():
    v_male = pick_voice("мужской", "Xb7hH8MSUJpSbSDYk0k2")
    assert v_male is not None
    assert v_male["gender"] == "мужской"

    v_female = pick_voice("женский", "EXAVITQu4vr4xnSDxMaL")
    assert v_female is not None
    assert v_female["gender"] == "женский"


@pytest.mark.asyncio
async def test_execute_orchestrator_reply_set_voice(monkeypatch):
    p = Project(slug="test-voice-proj", title="Test Voice", meta={})
    p.id = 55
    mock_session = AsyncMock()
    monkeypatch.setattr("app.web.routers.db_browser.commit_with_retry", AsyncMock())

    reply = 'Поменял голос озвучки на мужской.\n\n{"actions":[{"set_voice":{"voice":"мужской"}}]}'

    res = await _execute_orchestrator_reply(
        mock_session,
        p,
        reply,
        diagnose_only=False,
        canvas_keymap={},
        diag_lines=[],
        body_message="поменяй голос на мужской",
    )

    assert any("set_voice" in a for a in res["actions_run"])
    nsp = (p.meta or {}).get("node_step_params", {})
    assert "audio" in nsp
    assert "elevenlabs_voice_id" in nsp["audio"]
