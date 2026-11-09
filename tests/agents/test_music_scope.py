import asyncio

from app.orchestrator.agents import music_scope


def test_volume_direction():
    assert music_scope.volume_direction("сделай музыку потише") == -1
    assert music_scope.volume_direction("музыку погромче") == 1
    assert music_scope.volume_direction("поставь громкость 50") == 0
    assert music_scope.volume_direction("привет, как дела?") == 0


def test_quieter_never_mutes():
    assert music_scope.shifted_level(20, -1) == 13
    assert music_scope.shifted_level(6, -1) == 5
    assert music_scope.shifted_level(5, -1) == 5
    assert music_scope.shifted_level(0, 1) == 5


def test_plan_shifts_from_current_and_remounts(monkeypatch):
    async def level(pid: int) -> int:
        return 70

    monkeypatch.setattr(music_scope, "_current_level", level)
    plan = asyncio.run(music_scope.music_volume_plan("перемонтируй с музыкой потише", 4))
    assert plan is not None
    assert [s.action for s in plan] == ["montage.set_assemble_params", "montage.run_montage"]
    assert plan[0].params == {"project_id": 4, "bgm_level": 46}

    only = asyncio.run(music_scope.music_volume_plan("музыку погромче в 7 проекте", None))
    assert only is not None
    assert [s.action for s in only] == ["montage.set_assemble_params"]
    assert only[0].params == {"project_id": 7, "bgm_level": 94}
