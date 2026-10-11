#!/usr/bin/env python3
"""将结构化打斗设计按平台画像编译为模型执行 Prompt。"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILES_PATH = ROOT / "references" / "platform-profiles.json"
GLOBAL_HIGH_ENERGY_BLOCK = (
    "高速运镜；超然打斗镜头；高速环绕运镜；快推快拉；子弹时间；快切镜头；"
    "同场协同合击；爆点密集；15秒内持续高燃。"
)


def _normalize_platform_name(name: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", name.casefold())


def _vfx_description(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("description") or "")
    return str(item)


def _structured_vfx(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("description"), str)
        and bool(item["description"].strip())
        and isinstance(item.get("role"), str)
        and bool(item["role"].strip())
        and isinstance(item.get("priority"), (int, float))
        and not isinstance(item.get("priority"), bool)
        and isinstance(item.get("causal_binding"), str)
        and bool(item["causal_binding"].strip())
    )


def load_platform_profiles(path: Path | None = None) -> dict[str, dict[str, Any]]:
    profile_path = path or DEFAULT_PROFILES_PATH
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or "generic" not in profiles:
        raise ValueError("platform profile file must contain profiles.generic")
    return profiles


def resolve_platform(name: str, profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    requested = str(name or "").strip()
    normalized = _normalize_platform_name(requested)
    for profile in profiles.values():
        candidates = [profile.get("id", ""), profile.get("display_name", ""), *profile.get("aliases", [])]
        if normalized and any(_normalize_platform_name(str(candidate)) == normalized for candidate in candidates):
            resolved = copy.deepcopy(profile)
            resolved["requested_name"] = requested
            return resolved
    fallback = copy.deepcopy(profiles["generic"])
    fallback["requested_name"] = requested
    return fallback


def _issue(severity: str, code: str, message: str, beat_id: str | None = None) -> dict[str, Any]:
    issue: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if beat_id:
        issue["beat_id"] = beat_id
    return issue


_SEEDANCE_REFERENCE_TYPES = {"image", "video", "audio"}
_SEEDANCE_REFERENCE_ROLES = {
    "character_identity",
    "scene_layout",
    "prop_weapon",
    "style",
    "motion_camera",
    "previs_blocking",
    "clay_render",
    "audio_dialogue",
    "creative_reference",
}


def _timestamp_range(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*s?\s*",
        value,
    )
    if not match:
        return None
    start, end = float(match.group(1)), float(match.group(2))
    return (start, end) if end > start else None


def _audit_seedance_extensions(
    spec: dict[str, Any], profile: dict[str, Any], duration: Any, references: dict[str, Any], issues: list[dict[str, Any]]
) -> None:
    if profile.get("id") != "seedance-2.5":
        return

    manifest = spec.get("reference_manifest")
    reference_total = sum(
        references.get(field, 0) if isinstance(references.get(field, 0), int) else 0
        for field in ("images", "videos", "audios")
    )
    if manifest is None:
        if reference_total:
            issues.append(_issue("warning", "SEEDANCE_REFERENCE_MANIFEST_MISSING", "Seedance 2.5 有参考文件但缺少 reference_manifest；编译器无法显式声明每个 @Image/@Video/@Audio 的职责"))
    elif not isinstance(manifest, list):
        issues.append(_issue("error", "INVALID_REFERENCE_MANIFEST", "reference_manifest 必须是对象列表"))
    else:
        seen_ids: set[str] = set()
        for index, item in enumerate(manifest, 1):
            item_id = f"reference-{index}"
            if not isinstance(item, dict):
                issues.append(_issue("error", "INVALID_REFERENCE_ENTRY", "reference_manifest 每项必须是对象", item_id))
                continue
            raw_id = item.get("id")
            if not isinstance(raw_id, str) or not raw_id.strip():
                issues.append(_issue("error", "INVALID_REFERENCE_ENTRY", "参考项必须有非空 id", item_id))
                continue
            item_id = raw_id.strip()
            if item_id in seen_ids:
                issues.append(_issue("error", "DUPLICATE_REFERENCE_ID", f"参考 id 重复：{item_id}", item_id))
            seen_ids.add(item_id)
            ref_type = str(item.get("type") or "").casefold().strip()
            if ref_type not in _SEEDANCE_REFERENCE_TYPES:
                issues.append(_issue("error", "INVALID_REFERENCE_TYPE", f"{item_id} 的 type 必须是 image、video 或 audio", item_id))
            elif not re.fullmatch(rf"@{ref_type.title()}\s+\d+", item_id, re.IGNORECASE):
                issues.append(_issue("error", "REFERENCE_ID_NOT_EXPLICIT", f"{item_id} 必须使用 @Image/@Video/@Audio 编号", item_id))
            role = str(item.get("role") or "").strip()
            if not role:
                issues.append(_issue("error", "REFERENCE_ROLE_MISSING", f"{item_id} 缺少 role", item_id))
            elif role not in _SEEDANCE_REFERENCE_ROLES:
                issues.append(_issue("warning", "REFERENCE_ROLE_CUSTOM", f"{item_id} 使用自定义职责 {role}；请确保它不会同时承担多个互相冲突的职责", item_id))
            scope = item.get("scope")
            if not isinstance(scope, str) or not scope.strip():
                issues.append(_issue("error", "REFERENCE_SCOPE_MISSING", f"{item_id} 缺少非空 scope", item_id))
            if "entity" in item and (not isinstance(item.get("entity"), str) or not item["entity"].strip()):
                issues.append(_issue("error", "REFERENCE_ENTITY_INVALID", f"{item_id} 的 entity 必须是非空字符串", item_id))
        manifest_counts = {ref_type: 0 for ref_type in _SEEDANCE_REFERENCE_TYPES}
        for item in manifest:
            if isinstance(item, dict):
                ref_type = str(item.get("type") or "").casefold().strip()
                if ref_type in manifest_counts:
                    manifest_counts[ref_type] += 1
        declared_counts = {
            "image": references.get("images", 0),
            "video": references.get("videos", 0),
            "audio": references.get("audios", 0),
        }
        for ref_type, declared in declared_counts.items():
            if isinstance(declared, int) and manifest_counts[ref_type] != declared:
                issues.append(_issue("warning", "SEEDANCE_MANIFEST_COUNT_MISMATCH", f"reference_manifest 的 {ref_type} 数量为 {manifest_counts[ref_type]}，references 声明为 {declared}；请确认每个文件都有职责"))

    edit_plan = spec.get("edit_plan")
    if edit_plan is None:
        return
    if not isinstance(edit_plan, dict):
        issues.append(_issue("error", "INVALID_EDIT_PLAN", "edit_plan 必须是对象"))
        return
    mode = str(edit_plan.get("mode") or "new_generation").strip().casefold()
    if mode not in {"new_generation", "timestamp_edit"}:
        issues.append(_issue("error", "INVALID_EDIT_MODE", "edit_plan.mode 必须是 new_generation 或 timestamp_edit"))
        return
    if mode != "timestamp_edit":
        return
    if not isinstance(edit_plan.get("source"), str) or not edit_plan["source"].strip():
        issues.append(_issue("error", "EDIT_SOURCE_MISSING", "timestamp_edit 必须声明 source，例如 @Video 1"))
    keep = edit_plan.get("keep")
    if not isinstance(keep, list) or not keep or not all(isinstance(item, str) and item.strip() for item in keep):
        issues.append(_issue("error", "EDIT_KEEP_MISSING", "timestamp_edit 必须声明要保留的身份、动作、灯光或声音范围"))
    changes = edit_plan.get("changes")
    if not isinstance(changes, list) or not changes:
        issues.append(_issue("error", "EDIT_CHANGES_MISSING", "timestamp_edit 至少需要一条 changes"))
        return
    for index, change in enumerate(changes, 1):
        change_id = f"change-{index}"
        if not isinstance(change, dict):
            issues.append(_issue("error", "INVALID_EDIT_CHANGE", "edit_plan.changes 每项必须是对象", change_id))
            continue
        parsed = _timestamp_range(change.get("time_range"))
        if parsed is None:
            issues.append(_issue("error", "INVALID_EDIT_RANGE", "局部编辑 time_range 必须是 start-end 秒区间，例如 06-12s", change_id))
        elif isinstance(duration, (int, float)) and (parsed[0] < 0 or parsed[1] > float(duration)):
            issues.append(_issue("error", "EDIT_RANGE_OUT_OF_BOUNDS", "局部编辑区间不能超出项目时长", change_id))
        if not isinstance(change.get("change"), str) or not change["change"].strip():
            issues.append(_issue("error", "EDIT_CHANGE_MISSING", "局部编辑必须说明只修改什么", change_id))


def _audit_high_energy_map(project: dict[str, Any], beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    high_energy_map = project.get("high_energy_map")
    required_map_fields = (
        "high_speed_follow",
        "controlled_orbit",
        "push_or_pull",
        "bullet_time",
        "action_driven_cut",
        "same_scene_chain",
        "dense_impacts",
    )
    if not isinstance(high_energy_map, dict) or any(not high_energy_map.get(field) for field in required_map_fields):
        return [_issue("error", "HIGH_ENERGY_MAP_INCOMPLETE", "项目必须把固定高燃块逐项映射到具体 beat")]

    beat_by_id = {str(beat.get("id")): beat for beat in beats if beat.get("id")}

    def mapped_beat(field: str) -> dict[str, Any] | None:
        return beat_by_id.get(str(high_energy_map.get(field)))

    mapping_checks = (
        ("high_speed_follow", ["跟进", "跟拍", "追踪"]),
        ("controlled_orbit", ["环绕", "弧线"]),
        ("push_or_pull", ["推", "拉"]),
    )
    for field, tokens in mapping_checks:
        mapped = mapped_beat(field)
        operators_text = "".join(str(item) for item in ((mapped or {}).get("camera") or {}).get("operators") or [])
        if not mapped or not any(token in operators_text for token in tokens):
            issues.append(_issue("error", "HIGH_ENERGY_MAP_MISMATCH", f"{field} 未映射到含对应主运镜的 beat"))
    camera_mapping_ids = [str(high_energy_map.get(field)) for field, _ in mapping_checks]
    if len(set(camera_mapping_ids)) != len(camera_mapping_ids):
        issues.append(_issue("error", "HIGH_ENERGY_CAMERA_REUSE", "跟进、环绕、推拉必须分配到不同 beat，不能塞进同一镜头"))
    bullet_beat = mapped_beat("bullet_time")
    if not bullet_beat or not (bullet_beat.get("bullet_time") or {}).get("enabled"):
        issues.append(_issue("error", "HIGH_ENERGY_MAP_MISMATCH", "bullet_time 未映射到实际启用局部子弹时间的 beat"))
    cut_beat = mapped_beat("action_driven_cut")
    cut_text = str((cut_beat or {}).get("transition") or "")
    if not cut_beat or not any(token in cut_text for token in ("切", "转场", "遮挡", "匹配")):
        issues.append(_issue("error", "HIGH_ENERGY_MAP_MISMATCH", "action_driven_cut 未映射到动作驱动转场 beat"))

    for field in ("same_scene_chain", "dense_impacts"):
        mapped_ids = high_energy_map.get(field)
        if not isinstance(mapped_ids, list) or len(mapped_ids) < 2 or any(str(beat_id) not in beat_by_id for beat_id in mapped_ids):
            issues.append(_issue("error", "HIGH_ENERGY_MAP_MISMATCH", f"{field} 必须映射到至少两个存在的 beat"))
        elif len({str(beat_id) for beat_id in mapped_ids}) != len(mapped_ids):
            issues.append(_issue("error", "HIGH_ENERGY_MAP_DUPLICATE", f"{field} 不能用重复 beat 伪装为连续链"))
    scene_chain_ids = high_energy_map.get("same_scene_chain")
    if isinstance(scene_chain_ids, list) and all(str(beat_id) in beat_by_id for beat_id in scene_chain_ids):
        scene_ids = {str(beat_by_id[str(beat_id)].get("scene_id") or "") for beat_id in scene_chain_ids}
        if "" in scene_ids or len(scene_ids) != 1:
            issues.append(_issue("error", "HIGH_ENERGY_MAP_SCENE_BREAK", "same_scene_chain 中的 beat 必须共享同一 scene_id；换场应建立新的链并说明过渡"))
    return issues


def audit_project_spec(spec: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    """对结构化项目做可执行性预检，不把关键词存在当作结构成立。"""
    issues: list[dict[str, Any]] = []
    project = spec.get("project") or {}
    capabilities = profile.get("capabilities") or {}
    policy = profile.get("compiler_policy") or {}

    duration = project.get("duration_sec")
    minimum = capabilities.get("min_duration_sec")
    maximum = capabilities.get("max_duration_sec")
    if not isinstance(duration, (int, float)) or duration <= 0:
        issues.append(_issue("error", "INVALID_DURATION", "project.duration_sec 必须是正数"))
    else:
        if isinstance(minimum, (int, float)) and duration < minimum:
            issues.append(_issue("error", "DURATION_BELOW_PLATFORM_MIN", f"时长 {duration}s 低于平台下限 {minimum}s"))
        if isinstance(maximum, (int, float)) and duration > maximum:
            issues.append(_issue("error", "DURATION_ABOVE_PLATFORM_MAX", f"时长 {duration}s 超过平台上限 {maximum}s"))

    supported_ratios = capabilities.get("supported_aspect_ratios")
    aspect_ratio = project.get("aspect_ratio")
    if not isinstance(aspect_ratio, str) or not re.fullmatch(r"\d+(?:\.\d+)?:\d+(?:\.\d+)?", aspect_ratio):
        issues.append(_issue("error", "INVALID_ASPECT_RATIO", "project.aspect_ratio 必须使用正数比例格式，例如 16:9"))
    elif any(float(part) <= 0 for part in aspect_ratio.split(":")):
        issues.append(_issue("error", "INVALID_ASPECT_RATIO", "project.aspect_ratio 的两侧必须大于0"))
    if isinstance(supported_ratios, list) and aspect_ratio not in supported_ratios:
        issues.append(_issue("error", "UNSUPPORTED_ASPECT_RATIO", f"平台画像未列出画幅 {aspect_ratio}"))

    input_mode = str(project.get("input_mode") or "text").strip().casefold()
    workflows = capabilities.get("workflows")
    supported_modalities = capabilities.get("input_modalities")
    supported_modes = set(workflows) if isinstance(workflows, dict) else (
        {str(item).casefold() for item in supported_modalities} if isinstance(supported_modalities, list) else set()
    )
    if supported_modes and input_mode not in supported_modes:
        issues.append(_issue("error", "UNSUPPORTED_INPUT_MODE", f"当前平台画像不支持输入模式 {input_mode}"))

    references = spec.get("references") or {}
    for plural, singular, limit_field, code in (
        ("images", "image", "max_images", "REFERENCE_IMAGE_LIMIT"),
        ("videos", "video", "max_videos", "REFERENCE_VIDEO_LIMIT"),
        ("audios", "audio", "max_audios", "REFERENCE_AUDIO_LIMIT"),
    ):
        count = references.get(plural, 0)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            issues.append(_issue("error", "INVALID_REFERENCE_COUNT", f"references.{plural} 必须是非负整数"))
            continue
        limit = capabilities.get(limit_field)
        if isinstance(limit, int) and count > limit:
            issues.append(_issue("error", code, f"{singular} 参考数量 {count} 超过平台画像上限 {limit}"))

    reference_counts = {
        "images": references.get("images", 0) if isinstance(references.get("images", 0), int) else 0,
        "videos": references.get("videos", 0) if isinstance(references.get("videos", 0), int) else 0,
        "audios": references.get("audios", 0) if isinstance(references.get("audios", 0), int) else 0,
    }
    mixed_limit = capabilities.get("max_mixed_files")
    if isinstance(mixed_limit, int) and sum(reference_counts.values()) > mixed_limit:
        issues.append(_issue("error", "REFERENCE_MIXED_LIMIT", f"混合参考总数 {sum(reference_counts.values())} 超过平台画像上限 {mixed_limit}"))

    if isinstance(workflows, dict) and input_mode in workflows:
        workflow = workflows[input_mode]
        workflow_mismatch = False
        for plural in ("images", "videos", "audios"):
            exact = workflow.get(f"exact_{plural}")
            minimum_for_workflow = workflow.get(f"min_{plural}")
            maximum_for_workflow = workflow.get(f"max_{plural}")
            count = reference_counts[plural]
            if isinstance(exact, int) and count != exact:
                workflow_mismatch = True
            if isinstance(minimum_for_workflow, int) and count < minimum_for_workflow:
                workflow_mismatch = True
            if isinstance(maximum_for_workflow, int) and count > maximum_for_workflow:
                workflow_mismatch = True
        workflow_mixed_limit = workflow.get("max_mixed_files")
        if isinstance(workflow_mixed_limit, int) and sum(reference_counts.values()) > workflow_mixed_limit:
            workflow_mismatch = True
        if workflow_mismatch:
            issues.append(_issue("error", "WORKFLOW_REFERENCE_MISMATCH", f"输入模式 {input_mode} 的参考数量不符合平台工作流"))

    _audit_seedance_extensions(spec, profile, duration, references, issues)

    beats = spec.get("beats")
    if not isinstance(beats, list) or not beats:
        issues.append(_issue("error", "NO_BEATS", "至少需要一个动作节拍"))
        return issues
    if profile.get("id") == "seedance-2.5" and len(beats) not in range(4, 7):
        issues.append(_issue("warning", "SEEDANCE_SEGMENT_COUNT_GUIDANCE", f"Seedance 2.5 推荐 4–6 个功能段，当前有 {len(beats)} 个；按动作转折决定是否合并或拆分，不机械补动作"))

    required_text_fields = ("scene_id", "start_state", "lead_action", "response", "contact", "result", "end_state", "transition")
    camera_required_fields = ("trigger", "focus", "landing")
    previous_end: str | None = None
    bullet_time_count = 0
    active_duration = 0.0
    total_idle_duration = 0.0
    maximum_idle_gap = 0.0
    elapsed_timeline = 0.0
    first_contact_at: float | None = None

    for index, beat in enumerate(beats, 1):
        beat_id = str(beat.get("id") or f"beat-{index}")
        beat_duration = beat.get("duration_sec")
        if not isinstance(beat_duration, (int, float)) or beat_duration <= 0:
            issues.append(_issue("error", "INVALID_BEAT_DURATION", "duration_sec 必须是正数", beat_id))
        else:
            normalized_beat_duration = float(beat_duration)
            active_duration += normalized_beat_duration
            contact_offset = beat.get("contact_offset_sec")
            if not isinstance(contact_offset, (int, float)) or isinstance(contact_offset, bool) or contact_offset < 0 or contact_offset > normalized_beat_duration:
                issues.append(_issue("error", "INVALID_CONTACT_OFFSET", "contact_offset_sec 必须位于当前 beat 的 0..duration_sec 内", beat_id))
            elif first_contact_at is None:
                first_contact_at = elapsed_timeline + float(contact_offset)
        idle_after = beat.get("idle_after_sec", 0)
        if not isinstance(idle_after, (int, float)) or idle_after < 0:
            issues.append(_issue("error", "INVALID_IDLE_GAP", "idle_after_sec 必须是非负数", beat_id))
        else:
            normalized_idle = float(idle_after)
            total_idle_duration += normalized_idle
            maximum_idle_gap = max(maximum_idle_gap, normalized_idle)
        if isinstance(beat_duration, (int, float)) and not isinstance(beat_duration, bool) and beat_duration > 0:
            elapsed_timeline += float(beat_duration)
        if isinstance(idle_after, (int, float)) and not isinstance(idle_after, bool) and idle_after >= 0:
            elapsed_timeline += float(idle_after)
        for field in required_text_fields:
            if not isinstance(beat.get(field), str) or not beat[field].strip():
                issues.append(_issue("error", "MISSING_BEAT_FIELD", f"缺少非空字段 {field}", beat_id))

        start_state = beat.get("start_state")
        if previous_end is not None and start_state != previous_end:
            issues.append(_issue("error", "STATE_DISCONTINUITY", "本节拍起始状态未继承上一节拍结束状态", beat_id))
        previous_end = beat.get("end_state") if isinstance(beat.get("end_state"), str) else None

        camera = beat.get("camera") or {}
        operators = camera.get("operators") or []
        if not isinstance(operators, list):
            issues.append(_issue("error", "INVALID_CAMERA_OPERATORS", "camera.operators 必须是列表", beat_id))
            operators = []
        camera_categories = (
            ("follow", ("跟进", "跟拍", "追踪")),
            ("orbit", ("环绕", "弧线")),
            ("push_pull", ("快推", "快拉", "推进", "拉远")),
            ("whip", ("甩移", "甩镜")),
            ("lateral_vertical", ("横移", "升降", "俯冲", "摇镜")),
        )
        for operator in operators:
            operator_text = str(operator)
            matched_categories = {
                category for category, tokens in camera_categories if any(token in operator_text for token in tokens)
            }
            if len(matched_categories) > 1:
                issues.append(_issue("error", "CAMERA_OPERATOR_COMPOUND", "一个 camera.operators 条目只能表达一种主运镜，不能用复合字符串绕过预算", beat_id))
        max_camera = int(policy.get("max_camera_operators_per_beat", 1))
        if len(operators) > max_camera:
            issues.append(_issue("error", "CAMERA_OVERLOAD", f"本节拍有 {len(operators)} 个主运镜，平台策略预算为 {max_camera}", beat_id))
        for field in camera_required_fields:
            if not isinstance(camera.get(field), str) or not camera[field].strip():
                issues.append(_issue("error", "MISSING_CAMERA_FIELD", f"缺少 camera.{field}", beat_id))

        active_subjects = beat.get("active_subjects") or []
        max_subjects = int(policy.get("max_active_subjects_per_beat", 2))
        if isinstance(active_subjects, list) and len(active_subjects) > max_subjects:
            issues.append(_issue("error", "SUBJECT_OVERLOAD", f"活动主体 {len(active_subjects)} 个，超过平台策略预算 {max_subjects} 个；必须改写为主动作+支援结果或拆 beat", beat_id))

        micro_actions = beat.get("micro_actions") or []
        max_micro_actions = int(policy.get("max_micro_actions_per_beat", 4))
        if isinstance(micro_actions, list) and len(micro_actions) > max_micro_actions:
            issues.append(_issue("error", "ACTION_OVERLOAD", f"微动作 {len(micro_actions)} 个，超过平台策略预算 {max_micro_actions} 个；必须拆分因果链", beat_id))

        vfx_systems = beat.get("vfx_systems") or []
        max_vfx = int(policy.get("max_vfx_systems_per_beat", 2))
        if isinstance(vfx_systems, list) and len(vfx_systems) > max_vfx:
            if all(_structured_vfx(item) for item in vfx_systems):
                issues.append(_issue("warning", "VFX_OVERLOAD", f"独立 VFX {len(vfx_systems)} 套，编译器将按 role/priority/causal_binding 保留 {max_vfx} 套", beat_id))
            else:
                issues.append(_issue("error", "VFX_OVERLOAD_UNSAFE", "VFX 超预算时必须提供 description/role/priority/causal_binding，禁止按输入顺序盲切", beat_id))

        bullet_time = beat.get("bullet_time") or {}
        if bullet_time.get("enabled"):
            bullet_time_count += 1
            if not str(bullet_time.get("trigger") or "").strip():
                issues.append(_issue("error", "BULLET_TIME_NO_TRIGGER", "子弹时间必须绑定接触、闪避、反转或终局触发", beat_id))
            if not str(bullet_time.get("return_action") or "").strip():
                issues.append(_issue("error", "BULLET_TIME_NO_RETURN", "子弹时间后必须写明恢复实时高速并接回的动作", beat_id))

        recommended_segment = policy.get("recommended_segment_sec")
        if (
            policy.get("split_when_overloaded")
            and isinstance(recommended_segment, (int, float))
            and isinstance(beat_duration, (int, float))
            and beat_duration > recommended_segment
        ):
            issues.append(_issue("error", "BEAT_REQUIRES_SPLIT", f"beat 时长 {beat_duration}s 超过平台单段策略 {recommended_segment}s，必须在自然动作转折处拆分", beat_id))

    if isinstance(duration, (int, float)) and duration > 0 and active_duration + total_idle_duration > float(duration) + 0.001:
        issues.append(_issue("error", "TIMELINE_OVERFLOW", "动作节拍与空档合计超过项目总时长"))
    elif profile.get("id") == "seedance-2.5" and isinstance(duration, (int, float)) and duration > 0:
        covered = active_duration + total_idle_duration
        if covered < float(duration) - 0.001:
            issues.append(_issue("warning", "SEEDANCE_TIMELINE_TAIL_FILLED", f"动作节拍只覆盖 {covered:g}s；编译器会用最后结束状态生成连续余势段，补足到 {duration:g}s"))

    if project.get("pace") == "high_speed":
        if bullet_time_count > 1:
            issues.append(_issue("warning", "TOO_MANY_BULLET_TIME_BEATS", "高速短片默认只保留一个主要局部子弹时间"))
        if isinstance(duration, (int, float)) and duration >= 10 and len(beats) < 5:
            issues.append(_issue("error", "TOO_FEW_HIGH_SPEED_BEATS", "10秒以上高速项目至少需要5个可辨认动作节拍，或改用非高速节奏模式"))
        if isinstance(duration, (int, float)) and duration > 0 and active_duration / float(duration) < 0.75:
            issues.append(_issue("error", "ACTIVE_COMBAT_RATIO_LOW", "高速项目的有效动作节拍未覆盖总时长的75%"))
        if maximum_idle_gap > 1.2:
            issues.append(_issue("error", "IDLE_GAP_TOO_LONG", "高速项目单次无攻防间隔不得超过1.2秒"))
        if first_contact_at is not None and first_contact_at > 1.5:
            issues.append(_issue("error", "FIRST_CONTACT_TOO_LATE", "高速项目首个可见接触/有效应对应在约1.5秒内发生"))

    issues.extend(_audit_high_energy_map(project, beats))
    return issues


def _format_beat(beat: dict[str, Any], index: int, structured_shot: bool = False) -> str:
    beat_id = str(beat.get("id") or f"beat-{index}")
    camera = beat.get("camera") or {}
    operator = "、".join(str(item) for item in camera.get("operators") or []) or "稳定读取"
    parts = [
        f"节奏：约{beat.get('duration_sec', '')}秒有效动作，之后空档不超过{beat.get('idle_after_sec', 0)}秒",
        f"场景：{beat.get('scene_id', '')}",
        f"起始：{beat.get('start_state', '')}",
        f"主攻：{beat.get('lead_action', '')}",
        f"应对：{beat.get('response', '')}",
        f"接触：{beat.get('contact', '')}",
        f"结果：{beat.get('result', '')}",
        f"摄影：由{camera.get('trigger', '')}触发{operator}，锁定{camera.get('focus', '')}，落到{camera.get('landing', '')}",
        f"结束状态：{beat.get('end_state', '')}",
        f"衔接：{beat.get('transition', '')}",
    ]
    vfx = beat.get("vfx_systems") or []
    if vfx:
        parts.append("反馈：" + "、".join(_vfx_description(item) for item in vfx))
    bullet_time = beat.get("bullet_time") or {}
    if bullet_time.get("enabled"):
        parts.append(
            f"局部子弹时间只发生在{bullet_time.get('trigger', '')}；{bullet_time.get('return_action', '')}"
        )
    prefix = f"[Shot {index}]" if structured_shot else f"【{beat_id}】"
    return prefix + " " + "；".join(parts) + "。"


def _format_beat_compact(beat: dict[str, Any], index: int) -> str:
    camera = beat.get("camera") or {}
    operator = "、".join(str(item) for item in camera.get("operators") or []) or "稳定读取"
    vfx = beat.get("vfx_systems") or []
    bullet_time = beat.get("bullet_time") or {}
    parts = [
        f"【段{index}】{beat.get('start_state', '')}",
        f"{beat.get('lead_action', '')}；{beat.get('response', '')}",
        f"{beat.get('contact', '')}，{beat.get('result', '')}",
        f"镜头{operator}锁定{camera.get('focus', '')}，落到{camera.get('landing', '')}",
        f"结束：{beat.get('end_state', '')}",
        f"衔接：{beat.get('transition', '')}",
    ]
    if vfx:
        parts.append("反馈：" + "、".join(_vfx_description(item) for item in vfx))
    if bullet_time.get("enabled"):
        parts.append(f"{bullet_time.get('trigger', '')}短促局部子弹时间；{bullet_time.get('return_action', '')}")
    return "；".join(parts) + "。"


def _format_seedance_seconds(value: float) -> str:
    if abs(value - round(value)) < 0.001:
        return f"{int(round(value)):02d}"
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _seedance_timeline(working_spec: dict[str, Any], duration: float) -> tuple[list[str], list[dict[str, Any]]]:
    """把 beat + 余势编译为无空缺的累计区间；尾段只继承最终状态，不新增独立主动作。"""
    lines: list[str] = []
    records: list[dict[str, Any]] = []
    cursor = 0.0
    beats = working_spec.get("beats") or []
    last_beat: dict[str, Any] | None = None
    for index, beat in enumerate(beats, 1):
        span = float(beat.get("duration_sec", 0)) + float(beat.get("idle_after_sec", 0) or 0)
        if span <= 0 or cursor >= duration:
            continue
        start = cursor
        end = min(cursor + span, duration)
        beat_id = str(beat.get("id") or f"beat-{index}")
        camera = beat.get("camera") or {}
        operator = "、".join(str(item) for item in camera.get("operators") or []) or "稳定读取"
        idle_note = (
            f"有效动作约{beat.get('duration_sec', '')}s，随后余势/空档约{beat.get('idle_after_sec', 0)}s；"
            if float(beat.get("idle_after_sec", 0) or 0) > 0
            else ""
        )
        lines.append(
            f"[{_format_seedance_seconds(start)}–{_format_seedance_seconds(end)}s] "
            f"{idle_note}主动作：{beat.get('lead_action', '')}；主运镜：{operator}；"
            f"应对/接触：{beat.get('response', '')}；{beat.get('contact', '')}；"
            f"结果：{beat.get('result', '')}；结束状态：{beat.get('end_state', '')}；"
            f"衔接：{beat.get('transition', '')}。"
        )
        records.append({"beat_id": beat_id, "start_sec": round(start, 3), "end_sec": round(end, 3)})
        cursor = end
        last_beat = beat
    if cursor < duration:
        end_state = str((last_beat or {}).get("end_state") or "保持当前战斗状态")
        transition = str((last_beat or {}).get("transition") or "完成镜头收束")
        lines.append(
            f"[{_format_seedance_seconds(cursor)}–{_format_seedance_seconds(duration)}s] "
            f"延续段：保持最后结束状态“{end_state}”，只表现余势、呼吸、环境响应和镜头收束，"
            f"不新增独立主动作；{transition}。"
        )
        records.append({"beat_id": "continuity-tail", "start_sec": round(cursor, 3), "end_sec": round(duration, 3)})
    return lines, records


def _format_seedance_reference_manifest(spec: dict[str, Any]) -> list[str]:
    manifest = spec.get("reference_manifest")
    if not isinstance(manifest, list) or not manifest:
        return ["- none supplied; do not infer identity, motion or scene responsibility from an unlabeled file"]
    lines: list[str] = []
    groups: dict[str, list[str]] = {}
    for item in manifest:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "reference")
        ref_type = str(item.get("type") or "unknown")
        role = str(item.get("role") or "unspecified")
        scope = str(item.get("scope") or "unspecified")
        entity = str(item.get("entity") or "")
        suffix = f"; entity={entity}" if entity else ""
        lines.append(f"- {item_id} ({ref_type}; role={role}; scope={scope}{suffix})")
        if entity:
            groups.setdefault(entity, []).append(item_id)
    if groups:
        lines.append("same_entity_groups:")
        for entity, ids in groups.items():
            lines.append(f"- {entity}: {', '.join(ids)}; reconcile these views before inheriting appearance")
    return lines


def _format_seedance_edit_plan(spec: dict[str, Any]) -> list[str]:
    edit_plan = spec.get("edit_plan")
    if not isinstance(edit_plan, dict):
        return ["mode: new_generation"]
    mode = str(edit_plan.get("mode") or "new_generation")
    if mode != "timestamp_edit":
        return [f"mode: {mode}"]
    lines = [
        f"mode: timestamp_edit; source: {edit_plan.get('source', '')}",
        "keep: " + ", ".join(str(item) for item in edit_plan.get("keep") or []),
    ]
    for change in edit_plan.get("changes") or []:
        if isinstance(change, dict):
            lines.append(f"change only {change.get('time_range', '')}: {change.get('change', '')}")
    lines.append("all unlisted time ranges preserve the source video's identity, action, lighting, audio and continuity")
    return lines


def _format_seedance_audio(spec: dict[str, Any]) -> list[str]:
    audio = spec.get("audio")
    if isinstance(audio, str) and audio.strip():
        audio = {"environment": audio}
    if not isinstance(audio, dict):
        audio = {}
    layers = [
        ("dialogue", audio.get("dialogue") or spec.get("dialogue") or "no new dialogue; use only user-provided lines"),
        ("sound_effects", audio.get("sound_effects") or audio.get("sfx") or "contact, weapon, footstep and material response remain synchronized to visible action"),
        ("environment", audio.get("environment") or spec.get("soundscape") or "environmental bed supports spatial continuity without masking contact"),
        ("music", audio.get("music") or "not specified; do not let music replace action readability"),
    ]
    return [f"{name}: {value}" for name, value in layers]


def _platform_instruction(profile: dict[str, Any]) -> str:
    profile_id = profile.get("id")
    if profile_id == "happyhorse-1.0":
        return "短句执行：每段只保留一个主语、一条动作因果、一个主运镜和一个可见结果。"
    if profile_id == "minimax-h3":
        return "按 H3 Context-IR 友好的结构化 Shot 描述素材关系、动作状态、摄影触发与声音。"
    if profile_id == "seedance-2.5":
        return "先解耦 @Image/@Video/@Audio 的唯一职责，再用完整累计时间轴组织长叙事；每段只执行一个主动作、一个主运镜和一个可继承结果，局部编辑只改声明区间。"
    if profile_id == "seedance-2.0":
        return "使用多镜自然语言与状态接力；复杂合击按先后关系执行，不同时启动多套独立系统。"
    return "按保守通用策略执行；未知能力不启用首尾帧、负面词栏或多模态专属语法。"


def _apply_platform_downgrades(
    spec: dict[str, Any], profile: dict[str, Any], issues: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    working = copy.deepcopy(spec)
    policy = profile.get("compiler_policy") or {}
    beats = {str(beat.get("id")): beat for beat in working.get("beats") or []}
    applied: list[dict[str, Any]] = []
    for issue in issues:
        beat = beats.get(str(issue.get("beat_id") or ""))
        if beat is None:
            continue
        code = issue.get("code")
        if code == "VFX_OVERLOAD":
            limit = int(policy.get("max_vfx_systems_per_beat", 2))
            source_vfx = list(beat.get("vfx_systems") or [])
            role_rank = {
                "contact_feedback": 0,
                "state_change": 1,
                "environment_consequence": 2,
                "continuity_anchor": 3,
                "support_result": 4,
                "background": 8,
                "decoration": 9,
            }
            ranked = sorted(
                source_vfx,
                key=lambda item: (
                    role_rank.get(str(item.get("role")), 5),
                    -float(item.get("priority", 0)),
                ),
            )
            kept = ranked[:limit]
            beat["vfx_systems"] = kept
        else:
            continue
        applied_issue = copy.deepcopy(issue)
        if code == "VFX_OVERLOAD":
            applied_issue["retained"] = [_vfx_description(item) for item in kept]
            applied_issue["removed"] = [_vfx_description(item) for item in source_vfx if item not in kept]
        applied.append(applied_issue)
    return working, applied


def compile_project(spec: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """把已结构化的动作状态链编译为项目总稿与镜头级执行稿。"""
    issues = audit_project_spec(spec, profile)
    errors = [issue for issue in issues if issue["severity"] == "error"]
    warnings = [issue for issue in issues if issue["severity"] != "error"]
    if errors:
        codes = ", ".join(issue["code"] for issue in errors)
        raise ValueError(f"prompt preflight failed: {codes}")

    working_spec, applied_downgrades = _apply_platform_downgrades(spec, profile, warnings)
    project = working_spec.get("project") or {}
    beats = working_spec.get("beats") or []
    profile_id = str(profile.get("id") or "generic")
    prompt_style = str((profile.get("compiler_policy") or {}).get("prompt_style") or "")
    structured_shot = prompt_style == "structured_shots_with_context"
    compact_prompt = prompt_style == "short_compact_natural_language"
    beat_texts = [
        _format_beat_compact(beat, index) if compact_prompt else _format_beat(beat, index, structured_shot)
        for index, beat in enumerate(beats, 1)
    ]
    assets = "；".join(str(item) for item in working_spec.get("asset_locks") or []) or "未提供额外资产锁"
    negative_risks = "；".join(str(item) for item in working_spec.get("negative_risks") or []) or "只拦截本项目最高风险"
    instruction = _platform_instruction(profile)
    duration = project.get("duration_sec")
    duration_note = ""
    if isinstance(duration, (int, float)) and duration != 15:
        duration_label = int(duration) if float(duration).is_integer() else duration
        if duration > 15:
            duration_note = f"实际总时长为{duration_label}秒；固定块中的15秒只定义高燃段，不改变项目总时长。"
        else:
            duration_note = f"实际总时长为{duration_label}秒；固定块中的15秒不延长项目，按实际{duration_label}秒持续推进。"

    seedance_timeline_lines: list[str] = []
    seedance_timeline_records: list[dict[str, Any]] = []
    if profile_id == "seedance-2.5" and isinstance(duration, (int, float)) and duration > 0:
        seedance_timeline_lines, seedance_timeline_records = _seedance_timeline(working_spec, float(duration))

    if profile_id == "seedance-2.5":
        project_lines = [
            f"format: Seedance 2.5; duration: {project.get('duration_sec')}s; aspect_ratio: {project.get('aspect_ratio')}",
            f"project_level_high_energy_intent: {GLOBAL_HIGH_ENERGY_BLOCK}",
            *( [f"duration_interpretation: {duration_note}"] if duration_note else [] ),
            f"compiler_policy: {instruction}",
            f"subject_and_global_intent: {working_spec.get('global_intent', '')}",
            f"asset_invariants: {assets}",
            "reference_role_manifest:",
            *_format_seedance_reference_manifest(working_spec),
            "edit_plan:",
            *_format_seedance_edit_plan(working_spec),
            "timing:",
            *seedance_timeline_lines,
            "audio_and_constraints:",
            "audio_and_dialogue:",
            *_format_seedance_audio(working_spec),
            f"stability_constraints: {negative_risks}",
        ]
    elif structured_shot:
        project_lines = [
            f"platform: {profile.get('display_name', profile_id)}",
            f"duration: {project.get('duration_sec')}s; aspect_ratio: {project.get('aspect_ratio')}",
            f"project_level_high_energy_intent: {GLOBAL_HIGH_ENERGY_BLOCK}",
            *( [f"duration_interpretation: {duration_note}"] if duration_note else [] ),
            f"compiler_policy: {instruction}",
            f"asset_invariants: {assets}",
            "integrated_multimodal_description:",
            *beat_texts,
            f"overall_soundscape: {working_spec.get('soundscape') or '接触、破空与环境反馈同步动作；声音不替代可见接触。'}",
            f"stability_constraints: {negative_risks}",
        ]
    else:
        project_lines = [
            f"【平台】{profile.get('display_name', profile_id)}",
            f"【时长/画幅】{project.get('duration_sec')}秒，{project.get('aspect_ratio')}",
            f"【项目级高燃目标】{GLOBAL_HIGH_ENERGY_BLOCK}",
            *( [f"【时长解释】{duration_note}"] if duration_note else [] ),
            f"【平台编译策略】{instruction}",
            f"【总目标】{working_spec.get('global_intent', '')}",
            f"【资产稳定锁】{assets}",
            "【动作状态链】",
            *beat_texts,
            f"【负面约束】{negative_risks}",
        ]

    segment_prompts: list[str] = []
    seedance_record_by_beat = {record["beat_id"]: record for record in seedance_timeline_records}
    for index, beat in enumerate(beats, 1):
        local_header = f"[Shot {index}]" if structured_shot else f"【拆镜 {index}】"
        local_body = _format_beat_compact(beat, index) if compact_prompt else _format_beat(beat, index, False)
        local_constraints = "；".join(str(item) for item in working_spec.get("negative_risks") or [])
        seedance_record = seedance_record_by_beat.get(str(beat.get("id") or f"beat-{index}"))
        seedance_time = ""
        if seedance_record:
            seedance_time = f"累计时间段：{_format_seedance_seconds(seedance_record['start_sec'])}–{_format_seedance_seconds(seedance_record['end_sec'])}s；"
        segment_prompts.append(
            "\n".join(
                part
                for part in (
                    local_header,
                    "本镜保持连续高强度攻防；只执行本镜明确分配的主运镜，不继承项目级全部摄影操作。",
                    f"资产继承：{assets}",
                    seedance_time,
                    local_body,
                    f"稳定性：{local_constraints}" if local_constraints else "",
                )
                if part
            )
        )

    evidence_boundary = str(profile.get("evidence_notes") or "")
    if profile_id == "minimax-h3":
        evidence_boundary += " 结构化输出面向官方建议的 H3-Context-IR；未实际调用托管服务或本地权重。"
    else:
        evidence_boundary += " 当前仅完成文本与结构编译，未实际调用平台生成视频。"

    return {
        "platform_id": profile_id,
        "project_prompt": "\n".join(project_lines),
        "segment_prompts": segment_prompts,
        "timeline": seedance_timeline_records,
        "reference_manifest": copy.deepcopy(working_spec.get("reference_manifest") or []),
        "edit_plan": copy.deepcopy(working_spec.get("edit_plan") or {"mode": "new_generation"}),
        "audit": {"errors": errors, "warnings": warnings},
        "applied_downgrades": applied_downgrades,
        "compiler_policy_applied": copy.deepcopy(profile.get("compiler_policy") or {}),
        "evidence_boundary": evidence_boundary.strip(),
    }


def validate_prompt_delta(record: dict[str, Any]) -> list[str]:
    """校验用户补词前后差分；无同条件对照时不得声称候选因果。"""
    errors: list[str] = []

    def require_text(path: str, value: Any) -> None:
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{path} must be a non-empty string")

    def require_nonempty_list(path: str, value: Any) -> None:
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
            errors.append(f"{path} must be a non-empty string list")

    def require_object(path: str, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            errors.append(f"{path} must be an object")
            return {}
        return value

    allowed_top_level = {
        "schema_version", "delta_id", "project_id", "baseline_prompt", "user_delta", "production",
        "before", "after", "comparability", "effective_components", "evidence_status", "causal_status",
        "applicable_conditions", "non_applicable_conditions",
    }
    for extra in sorted(set(record) - allowed_top_level):
        errors.append(f"unexpected top-level field: {extra}")

    if record.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    require_text("delta_id", record.get("delta_id"))
    if isinstance(record.get("delta_id"), str) and not re.fullmatch(r"delta-[0-9a-f]{8}", record["delta_id"]):
        errors.append("delta_id must match delta-[0-9a-f]{8}")
    require_text("project_id", record.get("project_id"))
    require_text("baseline_prompt", record.get("baseline_prompt"))

    delta = require_object("user_delta", record.get("user_delta"))
    for extra in sorted(set(delta) - {"added", "removed"}):
        errors.append(f"unexpected user_delta field: user_delta.{extra}")
    added = delta.get("added")
    removed = delta.get("removed")
    if not isinstance(added, list) or not isinstance(removed, list) or not (added or removed):
        errors.append("user_delta.added/user_delta.removed must contain at least one change")
    elif not all(isinstance(item, str) and item.strip() for item in [*added, *removed]):
        errors.append("user_delta changes must be non-empty strings")

    production = require_object("production", record.get("production"))
    require_text("production.platform", production.get("platform"))
    if "model" in production and not isinstance(production.get("model"), str):
        errors.append("production.model must be a string")
    duration_sec = production.get("duration_sec")
    if "duration_sec" in production and not (
        duration_sec is None or (isinstance(duration_sec, (int, float)) and not isinstance(duration_sec, bool))
    ):
        errors.append("production.duration_sec must be a number or null")
    for field in ("aspect_ratio", "input_mode"):
        if field in production and production.get(field) is not None and not isinstance(production.get(field), str):
            errors.append(f"production.{field} must be a string or null")

    before = require_object("before", record.get("before"))
    after = require_object("after", record.get("after"))
    require_nonempty_list("before.issues", before.get("issues"))
    require_nonempty_list("after.changes", after.get("changes"))
    side_effects = after.get("side_effects")
    if not isinstance(side_effects, list) or not all(isinstance(item, str) and item.strip() for item in side_effects):
        errors.append("after.side_effects must be a string list")

    comparability = require_object("comparability", record.get("comparability"))
    for field in ("same_assets", "same_settings"):
        if not isinstance(comparability.get(field), bool):
            errors.append(f"comparability.{field} must be boolean")
    if "same_seed" in comparability and comparability.get("same_seed") is not None and not isinstance(comparability.get("same_seed"), bool):
        errors.append("comparability.same_seed must be boolean or null")
    require_text("comparability.notes", comparability.get("notes"))

    require_nonempty_list("effective_components", record.get("effective_components"))
    require_nonempty_list("applicable_conditions", record.get("applicable_conditions"))
    require_nonempty_list("non_applicable_conditions", record.get("non_applicable_conditions"))

    evidence_status = record.get("evidence_status")
    if evidence_status not in {"design_analysis", "user_attested", "agent_observed"}:
        errors.append("evidence_status must be design_analysis, user_attested, or agent_observed")
    causal_status = record.get("causal_status")
    if causal_status not in {"correlational", "causal_candidate"}:
        errors.append("causal_status must be correlational or causal_candidate")
    if causal_status == "causal_candidate" and not (
        comparability.get("same_assets") is True and comparability.get("same_settings") is True
    ):
        errors.append("causal_candidate requires same_assets=true and same_settings=true")
    if causal_status == "causal_candidate" and evidence_status not in {"user_attested", "agent_observed"}:
        errors.append("causal_candidate requires evidence_status=user_attested or agent_observed")
    return errors


def _read_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("input JSON root must be an object")
    return payload


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser("compile", help="编译结构化项目 JSON")
    compile_parser.add_argument("--input", required=True)
    compile_parser.add_argument("--platform", help="覆盖 project.platform")
    compile_parser.add_argument("--profiles", help="平台画像 JSON 路径")

    audit_parser = subparsers.add_parser("audit", help="只运行结构化预检")
    audit_parser.add_argument("--input", required=True)
    audit_parser.add_argument("--platform", help="覆盖 project.platform")
    audit_parser.add_argument("--profiles", help="平台画像 JSON 路径")

    delta_parser = subparsers.add_parser("validate-delta", help="校验用户补词差分 JSON")
    delta_parser.add_argument("--input", required=True)

    subparsers.add_parser("list-platforms", help="列出平台画像摘要")
    args = parser.parse_args(argv)

    try:
        if args.command == "validate-delta":
            errors = validate_prompt_delta(_read_json(args.input))
            _print_json({"valid": not errors, "errors": errors})
            return 1 if errors else 0

        profiles_path = Path(args.profiles) if getattr(args, "profiles", None) else None
        profiles = load_platform_profiles(profiles_path)
        if args.command == "list-platforms":
            _print_json(
                [
                    {"id": profile["id"], "display_name": profile["display_name"], "evidence_status": profile["evidence_status"]}
                    for profile in profiles.values()
                ]
            )
            return 0

        spec = _read_json(args.input)
        platform_name = args.platform or str((spec.get("project") or {}).get("platform") or "generic")
        profile = resolve_platform(platform_name, profiles)
        if args.command == "audit":
            issues = audit_project_spec(spec, profile)
            _print_json({"platform_id": profile["id"], "issues": issues})
            return 1 if any(issue["severity"] == "error" for issue in issues) else 0
        _print_json(compile_project(spec, profile))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _print_json({"error": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
