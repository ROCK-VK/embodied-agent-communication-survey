#!/usr/bin/env python3
"""Offline, rate-aware analysis for the five-run ESP32-C5 physical experiment.

This script only reads completed run directories and writes analysis products under
the supplied result root. A run is considered complete only when both
records.jsonl and summary.json exist, so a capture still in progress is reported
as pending instead of being mistaken for an empty run.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np


RUN_NAMES = ("static1", "blocked", "static2", "motion", "static3")
UINT32_MOD = 1 << 32
UINT32_HALF = 1 << 31
HEX_106_BYTES = re.compile(r"(?:[0-9a-fA-F]{2}){106}\Z")
VECTOR_FIELDS = (
    "rate_scope", "slot", "slot_label", "subcarrier_k", "physical_index_known",
    "packet_count", "unmasked_packet_count", "masked_packet_count",
    "raw_mean_amplitude", "raw_variance", "raw_std",
    "rms_norm_mean_amplitude", "rms_norm_variance", "rms_norm_std",
    "l2_norm_mean_amplitude", "l2_norm_variance", "l2_norm_std",
    "raw_allzero_ratio", "raw_allzero_candidate", "unmasked_allzero_ratio",
    "masked_first_word_invalid_count",
)


def json_key(value: Any) -> str:
    """Stable key for JSON scalars and composite values such as a rate object."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(value)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def flag_is_true(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return value is True or value == 1


def flag_is_known(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return value in (0, 1)
    if isinstance(value, str):
        return value.strip().lower() in ("0", "1", "true", "false", "yes", "no", "on", "off")
    return False


def write_csv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            clean = {}
            for key, value in row.items():
                if value is None:
                    clean[key] = ""
                elif isinstance(value, (dict, list, tuple)):
                    clean[key] = json.dumps(json_safe(value), ensure_ascii=False, separators=(",", ":"))
                elif isinstance(value, (float, np.floating)) and not math.isfinite(float(value)):
                    clean[key] = ""
                else:
                    clean[key] = value
            writer.writerow(clean)


def load_completed_run(run_dir: Path) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None, dict[str, Any]]:
    """Read only a completed capture pair; leave an active/incomplete run pending."""
    records_path = run_dir / "records.jsonl"
    summary_path = run_dir / "summary.json"
    state: dict[str, Any] = {"run_directory": str(run_dir)}
    if not run_dir.is_dir():
        return None, None, {**state, "status": "pending", "pending_reason": "run directory is missing; no data was synthesized"}
    if not records_path.is_file() or not summary_path.is_file():
        missing = []
        if not records_path.is_file():
            missing.append("records.jsonl")
        if not summary_path.is_file():
            missing.append("summary.json")
        return None, None, {
            **state,
            "status": "pending",
            "pending_reason": "incomplete run pair (" + ", ".join(missing) + "); records were not read",
        }
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
        if not isinstance(summary, dict):
            raise ValueError("summary root is not an object")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return None, None, {
            **state,
            "status": "pending",
            "pending_reason": "summary.json could not be read as a completed summary: " + str(exc),
        }

    events: list[dict[str, Any]] = []
    parse_errors = 0
    non_object_json = 0
    with records_path.open("r", encoding="utf-8-sig", errors="replace") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            if not isinstance(record, dict):
                non_object_json += 1
                continue
            events.append(record)
    state.update({
        "status": "ready" if events else ("completed_empty" if parse_errors == 0 and non_object_json == 0 else "completed_with_parse_errors"),
        "records_file": str(records_path),
        "summary_file": str(summary_path),
        "json_object_records_read": len(events),
        "json_parse_errors": parse_errors,
        "non_object_json_lines": non_object_json,
    })
    return events, summary, state


def event_is_uplink_data(event: dict[str, Any]) -> bool:
    return (
        int_or_none(event.get("frame_type")) == 2
        and int_or_none(event.get("to_ds")) == 1
        and int_or_none(event.get("from_ds")) == 0
    )


def has_correct_hex(event: dict[str, Any]) -> bool:
    raw_hex = event.get("data_hex")
    return isinstance(raw_hex, str) and HEX_106_BYTES.fullmatch(raw_hex) is not None


def get_filter_pipeline(events: list[dict[str, Any]], mac: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts: dict[str, int] = {"json_object_records": len(events)}
    current = list(events)

    source_matched = [e for e in current if str(e.get("source", "")).strip().lower() == mac]
    counts["source_match"] = len(source_matched)
    counts["excluded_source_mismatch"] = len(current) - len(source_matched)
    current = source_matched

    uplink = [e for e in current if event_is_uplink_data(e)]
    counts["uplink_data_to_ds1_from_ds0"] = len(uplink)
    counts["excluded_not_uplink_data"] = len(current) - len(uplink)
    current = uplink

    phy = [
        e for e in current
        if int_or_none(e.get("format")) == 1
        and int_or_none(e.get("second")) == 0
        and int_or_none(e.get("len")) == 106
    ]
    counts["format1_second0_len106"] = len(phy)
    counts["excluded_format_second_or_length"] = len(current) - len(phy)
    current = phy

    metadata_valid = [
        e for e in current
        if int_or_none(e.get("estimate_valid")) == 1 and int_or_none(e.get("rx_state")) == 0
    ]
    counts["estimate_valid1_rx_state0"] = len(metadata_valid)
    counts["excluded_metadata_invalid"] = len(current) - len(metadata_valid)
    current = metadata_valid

    copied = [
        e for e in current
        if int_or_none(e.get("copied")) == int_or_none(e.get("len"))
        and int_or_none(e.get("copied")) is not None
    ]
    counts["copied_equals_len"] = len(copied)
    counts["excluded_copy_length_mismatch"] = len(current) - len(copied)
    current = copied

    hex_correct = [e for e in current if has_correct_hex(e)]
    counts["raw_hex_exactly_106_bytes"] = len(hex_correct)
    counts["excluded_hex_length_or_characters"] = len(current) - len(hex_correct)
    current = hex_correct

    nonempty = [e for e in current if bool(e.get("data_hex", ""))]
    counts["nonempty_data"] = len(nonempty)
    counts["excluded_empty_data"] = len(current) - len(nonempty)
    current = nonempty

    first_word_known = [e for e in current if flag_is_known(e.get("first_word_invalid"))]
    counts["first_word_invalid_field_present"] = len(first_word_known)
    counts["excluded_missing_first_word_invalid"] = len(current) - len(first_word_known)
    return first_word_known, counts


def decode_i12(low_byte: np.ndarray, high_byte: np.ndarray) -> np.ndarray:
    """Decode signed 12-bit values stored in the low 12 bits of LE 16-bit words."""
    value = low_byte.astype(np.uint16) | ((high_byte.astype(np.uint16) & 0x0F) << 8)
    signed = value.astype(np.int32)
    signed[signed & 0x800 != 0] -= 0x1000
    return signed


def decoder_description(mode: str) -> dict[str, Any]:
    if mode == "12":
        return {
            "mode": "12-bit",
            "representation": "26 complex packed slots from bytes 0..103; each four bytes contain real then imaginary, each as low-12-bit signed little-endian values",
            "sign_extension": "mask to 12 bits, then subtract 4096 when bit 11 is set",
            "trailing_bytes": "bytes 104..105 preserved as uninterpreted hex and counted; no numeric/PHY meaning is assigned",
            "slot_label": "packed_complex_slot0..25",
            "physical_subcarrier_mapping_known": False,
            "dc_mask_applied": False,
            "first_word_invalid_mask": "mask packed_complex_slot0 when true; the original 4 bytes remain in records.jsonl",
            "source": "ESP-IDF issue #18493 maintainer discussion; exact 5 GHz C5 slot-to-carrier mapping remains unresolved here",
            "source_url": "https://github.com/espressif/esp-idf/issues/18493",
        }
    return {
        "mode": "8-bit",
        "representation": "53 signed int8 [Imag, Real] pairs from bytes 0..105; complex = Real + j*Imag",
        "slot_label": "C5 non-HT order k=0..26,-26..-1",
        "physical_subcarrier_mapping_known": "guide-defined 8-bit mapping; not validated on this board/mode",
        "dc_mask_applied": True,
        "first_word_invalid_mask": "mask the first two complex pairs when true; the original 4 bytes remain in records.jsonl",
        "source": "Guide-described 8-bit path only; issue18493 wording differs on I/Q order. Do not apply to mode0 packed data. This optional path was not validated on this board.",
        "source_url": "https://docs.espressif.com/projects/esp-idf/en/v5.5.5/esp32c5/api-guides/wifi.html",
    }


def decode_event(event: dict[str, Any], mode: str) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, bytes | None]:
    raw = bytes.fromhex(str(event["data_hex"]))
    first_invalid = flag_is_true(event.get("first_word_invalid"))
    if mode == "12":
        words = np.frombuffer(raw[:104], dtype=np.uint8).reshape(26, 4)
        real = decode_i12(words[:, 0], words[:, 1])
        imag = decode_i12(words[:, 2], words[:, 3])
        iq = real.astype(np.float64) + 1j * imag.astype(np.float64)
        mask = np.zeros(26, dtype=bool)
        if first_invalid:
            mask[0] = True
        components = np.column_stack((real, imag)).reshape(-1)
        return iq, mask, None, bytes(raw[104:106])

    # ESP-IDF C5 8-bit order is [Imag, Real] for each complex sample.
    pairs = np.frombuffer(raw, dtype=np.int8).reshape(53, 2)
    imag = pairs[:, 0].astype(np.float64)
    real = pairs[:, 1].astype(np.float64)
    iq = real + 1j * imag
    carriers = np.asarray(list(range(0, 27)) + list(range(-26, 0)), dtype=np.int32)
    mask = carriers == 0
    if first_invalid:
        mask[:2] = True
    components = pairs.astype(np.int16, copy=False).reshape(-1)
    return iq, mask, components, None


def unwrap_timestamps(events: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    raw_values = np.full(len(events), np.nan, dtype=np.float64)
    unwrapped = np.full(len(events), np.nan, dtype=np.float64)
    wraps = 0
    wrap_events = 0
    large_forward_jumps = 0
    previous: int | None = None
    for index, event in enumerate(events):
        raw_number = int_or_none(event.get("timestamp"))
        if raw_number is None:
            continue
        raw = raw_number % UINT32_MOD
        raw_values[index] = raw
        if previous is not None:
            difference = raw - previous
            if difference < -UINT32_HALF:
                wraps += 1
                wrap_events += 1
            elif difference > UINT32_HALF:
                large_forward_jumps += 1
        unwrapped[index] = raw + wraps * UINT32_MOD
        previous = raw
    first_finite = np.flatnonzero(np.isfinite(unwrapped))
    if len(first_finite):
        unwrapped -= unwrapped[first_finite[0]]
    elapsed_s = unwrapped / 1_000_000.0
    return raw_values, unwrapped, {
        "detected_uint32_wraps": wrap_events,
        "large_forward_jumps_possible_out_of_order": large_forward_jumps,
        "missing_timestamps": int(np.count_nonzero(~np.isfinite(raw_values))),
        "elapsed_origin": "first analyzed packet timestamp; gaps reflect packet timing and are not resampled",
    }


def column_stats(values: np.ndarray, mask: np.ndarray) -> dict[str, np.ndarray]:
    valid = (~mask) & np.isfinite(values)
    count = np.sum(valid, axis=0).astype(np.int64)
    sums = np.sum(np.where(valid, values, 0.0), axis=0)
    means = np.full(values.shape[1], np.nan, dtype=np.float64)
    np.divide(sums, count, out=means, where=count > 0)
    centered = np.where(valid, values - means[None, :], 0.0)
    squared = np.sum(centered * centered, axis=0)
    variances = np.full(values.shape[1], np.nan, dtype=np.float64)
    np.divide(squared, count - 1, out=variances, where=count > 1)
    return {"count": count, "mean": means, "variance": variances, "std": np.sqrt(variances)}


def normalize_amplitudes(amplitudes: np.ndarray, masks: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    valid_amp = np.where(masks, np.nan, amplitudes)
    valid = ~masks
    l2_scale = np.sqrt(np.sum(np.where(valid, amplitudes * amplitudes, 0.0), axis=1))
    valid_count = np.sum(valid, axis=1)
    rms_scale = np.full(len(amplitudes), np.nan, dtype=np.float64)
    np.divide(l2_scale, np.sqrt(valid_count), out=rms_scale, where=valid_count > 0)
    l2_norm = np.full_like(amplitudes, np.nan, dtype=np.float64)
    rms_norm = np.full_like(amplitudes, np.nan, dtype=np.float64)
    np.divide(valid_amp, l2_scale[:, None], out=l2_norm, where=(l2_scale[:, None] > 0) & np.isfinite(valid_amp))
    np.divide(valid_amp, rms_scale[:, None], out=rms_norm, where=(rms_scale[:, None] > 0) & np.isfinite(valid_amp))
    return valid_amp, l2_norm, rms_norm, rms_scale


def mean_rows(values: np.ndarray, indices: np.ndarray) -> np.ndarray:
    if len(indices) == 0:
        return np.full(values.shape[1], np.nan, dtype=np.float64)
    sample = values[indices]
    valid = np.isfinite(sample)
    count = np.sum(valid, axis=0)
    sums = np.sum(np.where(valid, sample, 0.0), axis=0)
    result = np.full(values.shape[1], np.nan, dtype=np.float64)
    np.divide(sums, count, out=result, where=count > 0)
    return result


def make_run_data(events: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    decoded = [decode_event(event, mode) for event in events]
    slots = len(decoded[0][0]) if decoded else (26 if mode == "12" else 53)
    iq = np.empty((len(events), slots), dtype=np.complex128)
    masks = np.empty((len(events), slots), dtype=bool)
    component_parts: list[np.ndarray] = []
    tails: list[bytes] = []
    for index, (packet_iq, packet_mask, components, tail) in enumerate(decoded):
        iq[index, :] = packet_iq
        masks[index, :] = packet_mask
        if components is not None:
            component_parts.append(components)
        if tail is not None:
            tails.append(tail)
    amplitudes = np.abs(iq)
    raw_amp, l2_norm, rms_norm, rms_scale = normalize_amplitudes(amplitudes, masks)
    raw_ts, unwrapped_ts, timestamp_info = unwrap_timestamps(events)
    # The unwrapped axis is made relative to the first analyzed CSI packet.
    elapsed_s = unwrapped_ts / 1_000_000.0
    interval_s = np.full(len(events), np.nan, dtype=np.float64)
    if len(events) > 1:
        interval_s[1:] = np.diff(elapsed_s)

    if mode == "12":
        component_array = np.column_stack((iq.real, iq.imag)).reshape(-1) if len(events) else np.asarray([], dtype=np.float64)
        saturation_limit = {"negative_extreme": -2048, "positive_extreme": 2047, "bit_depth": 12}
        saturation_note = "12-bit component extrema; int8 saturation is not meaningful for packed 12-bit samples"
    else:
        component_array = np.concatenate(component_parts) if component_parts else np.asarray([], dtype=np.int16)
        saturation_limit = {"negative_extreme": -128, "positive_extreme": 127, "bit_depth": 8}
        saturation_note = "signed int8 component extrema"
    point_saturated = (
        (iq.real == saturation_limit["negative_extreme"])
        | (iq.real == saturation_limit["positive_extreme"])
        | (iq.imag == saturation_limit["negative_extreme"])
        | (iq.imag == saturation_limit["positive_extreme"])
    )
    if len(component_array):
        saturated_count = int(np.count_nonzero((component_array == saturation_limit["negative_extreme"]) | (component_array == saturation_limit["positive_extreme"])))
        saturation_ratio: float | None = saturated_count / int(component_array.size)
    else:
        saturated_count = 0
        saturation_ratio = None
    point_count = int(iq.size)
    saturated_point_count = int(np.count_nonzero(point_saturated))
    valid_point_mask = ~masks
    valid_iq = iq[valid_point_mask]
    valid_point_saturated = (
        (valid_iq.real == saturation_limit["negative_extreme"])
        | (valid_iq.real == saturation_limit["positive_extreme"])
        | (valid_iq.imag == saturation_limit["negative_extreme"])
        | (valid_iq.imag == saturation_limit["positive_extreme"])
    )
    valid_point_count = int(valid_iq.size)
    valid_saturated_point_count = int(np.count_nonzero(valid_point_saturated))

    return {
        "events": events,
        "iq": iq,
        "amplitudes": amplitudes,
        "raw_amp": raw_amp,
        "l2_norm": l2_norm,
        "rms_norm": rms_norm,
        "masks": masks,
        "rms_scale": rms_scale,
        "timestamp_raw": raw_ts,
        "timestamp_unwrapped_us": unwrapped_ts,
        "elapsed_s": elapsed_s,
        "interval_s": interval_s,
        "timestamp_info": timestamp_info,
        "saturation": {
            "component_count": int(component_array.size),
            "saturated_component_count": saturated_count,
            "component_saturation_ratio": saturation_ratio,
            "int8_saturation_ratio": saturation_ratio if mode == "8" else None,
            "complex_point_count": point_count,
            "complex_points_with_any_saturated_component": saturated_point_count,
            "complex_point_saturation_ratio": saturated_point_count / point_count if point_count else None,
            "unmasked_complex_point_count": valid_point_count,
            "unmasked_complex_points_with_any_saturated_component": valid_saturated_point_count,
            "unmasked_complex_point_saturation_ratio": valid_saturated_point_count / valid_point_count if valid_point_count else None,
            "limits": saturation_limit,
            "note": saturation_note,
        },
        "tail_bytes": tails,
    }


def rate_groups(events: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, event in enumerate(events):
        grouped[json_key(event.get("rate"))].append(index)
    return {key: np.asarray(indices, dtype=np.int64) for key, indices in grouped.items()}


def count_distribution(events: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(json_key(event.get(field)) for event in events).items()))


def distribution_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    format_rate_length = Counter()
    for event in events:
        key = "format=" + json_key(event.get("format")) + ";rate=" + json_key(event.get("rate")) + ";len=" + json_key(event.get("len"))
        format_rate_length[key] += 1
    return {
        "format_phy": count_distribution(events, "format"),
        "rate": count_distribution(events, "rate"),
        "length_bytes": count_distribution(events, "len"),
        "format_rate_length": dict(sorted(format_rate_length.items())),
    }


def tail_distribution(tails: list[bytes]) -> dict[str, Any]:
    if not tails:
        return {"count": 0, "byte0_hex": {}, "byte1_hex": {}, "pair_hex": {}}
    return {
        "count": len(tails),
        "byte0_hex": dict(sorted(Counter(f"{tail[0]:02x}" for tail in tails).items())),
        "byte1_hex": dict(sorted(Counter(f"{tail[1]:02x}" for tail in tails).items())),
        "pair_hex": dict(sorted(Counter(tail.hex() for tail in tails).items())),
        "interpretation": "uninterpreted trailing bytes; retained without a numeric or subcarrier claim",
    }


def vector_scopes(events: list[dict[str, Any]]) -> list[tuple[str, np.ndarray]]:
    all_indices = np.arange(len(events), dtype=np.int64)
    groups = rate_groups(events)
    scopes = [("all_rates", all_indices)]
    scopes.extend(("rate=" + key, indices) for key, indices in sorted(groups.items()))
    return scopes


def vector_statistics(run_data: dict[str, Any], indices: np.ndarray) -> dict[str, dict[str, np.ndarray]]:
    return {
        "raw": column_stats(run_data["raw_amp"][indices], run_data["masks"][indices]),
        "rms": column_stats(run_data["rms_norm"][indices], run_data["masks"][indices]),
        "l2": column_stats(run_data["l2_norm"][indices], run_data["masks"][indices]),
    }


def build_vector_rows(name: str, run_data: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    slot_count = run_data["amplitudes"].shape[1]
    if mode == "12":
        carriers: list[int | None] = [None] * slot_count
        labels = [f"packed_complex_slot{i}" for i in range(slot_count)]
    else:
        carrier_values = list(range(0, 27)) + list(range(-26, 0))
        carriers = carrier_values
        labels = [f"k{value}" for value in carrier_values]

    for scope, indices in vector_scopes(run_data["events"]):
        stats = vector_statistics(run_data, indices)
        amp = run_data["amplitudes"][indices]
        masks = run_data["masks"][indices]
        for slot in range(slot_count):
            allzero = float(np.mean(amp[:, slot] == 0.0)) if len(indices) else math.nan
            observed = ~masks[:, slot] if len(indices) else np.asarray([], dtype=bool)
            unmasked_allzero = float(np.mean(amp[observed, slot] == 0.0)) if np.any(observed) else math.nan
            rows.append({
                "rate_scope": scope,
                "slot": slot,
                "slot_label": labels[slot],
                "subcarrier_k": carriers[slot],
                "physical_index_known": mode == "8",
                "packet_count": int(len(indices)),
                "unmasked_packet_count": int(np.count_nonzero(observed)),
                "masked_packet_count": int(np.count_nonzero(masks[indices, slot])) if len(indices) else 0,
                "raw_mean_amplitude": stats["raw"]["mean"][slot],
                "raw_variance": stats["raw"]["variance"][slot],
                "raw_std": stats["raw"]["std"][slot],
                "rms_norm_mean_amplitude": stats["rms"]["mean"][slot],
                "rms_norm_variance": stats["rms"]["variance"][slot],
                "rms_norm_std": stats["rms"]["std"][slot],
                "l2_norm_mean_amplitude": stats["l2"]["mean"][slot],
                "l2_norm_variance": stats["l2"]["variance"][slot],
                "l2_norm_std": stats["l2"]["std"][slot],
                "raw_allzero_ratio": allzero,
                "raw_allzero_candidate": bool(len(indices) and allzero == 1.0),
                "unmasked_allzero_ratio": unmasked_allzero,
                "masked_first_word_invalid_count": int(np.count_nonzero(
                    run_data["masks"][indices, slot] & np.asarray([
                        flag_is_true(run_data["events"][i].get("first_word_invalid")) for i in indices
                    ], dtype=bool)
                )) if len(indices) else 0,
            })
    return rows


def selected_six_slots(run_data: dict[str, Any]) -> list[int]:
    if len(run_data["events"]) == 0:
        return []
    available = np.flatnonzero(np.any(~run_data["masks"], axis=0))
    if len(available) < 6:
        return [int(slot) for slot in available]
    positions = np.rint(np.linspace(0, len(available) - 1, 6)).astype(int)
    selected = np.unique(available[positions])
    return [int(slot) for slot in selected]


def build_timeseries_rows(run_data: dict[str, Any], mode: str) -> tuple[list[str], list[dict[str, Any]], list[int]]:
    selected = selected_six_slots(run_data)
    slots = run_data["amplitudes"].shape[1]
    fields = [
        "packet_index", "timestamp_raw_us_u32", "timestamp_unwrapped_us_from_origin", "elapsed_s_from_first_packet",
        "interval_from_previous_packet_s", "source", "ta", "ra", "format", "rate", "channel", "second",
        "len", "copied", "rssi", "first_word_invalid", "unmasked_slot_count",
        "mean_raw_amplitude", "mean_l2_normalized_amplitude", "mean_rms_normalized_amplitude",
        "l2_scale", "rms_scale", "tail_bytes_hex",
    ]
    for slot in range(slots):
        fields.extend((f"raw_amp_slot_{slot:02d}", f"rms_norm_amp_slot_{slot:02d}"))
    rows: list[dict[str, Any]] = []
    for index, event in enumerate(run_data["events"]):
        raw_values = run_data["raw_amp"][index]
        l2_values = run_data["l2_norm"][index]
        rms_values = run_data["rms_norm"][index]
        valid_amp = np.isfinite(raw_values)
        valid_count = int(np.count_nonzero(valid_amp))
        tail_hex = run_data["tail_bytes"][index].hex() if mode == "12" else ""
        row: dict[str, Any] = {
            "packet_index": index,
            "timestamp_raw_us_u32": run_data["timestamp_raw"][index],
            "timestamp_unwrapped_us_from_origin": run_data["timestamp_unwrapped_us"][index],
            "elapsed_s_from_first_packet": run_data["elapsed_s"][index],
            "interval_from_previous_packet_s": run_data["interval_s"][index],
            "source": event.get("source"),
            "ta": event.get("ta"),
            "ra": event.get("ra"),
            "format": event.get("format"),
            "rate": event.get("rate"),
            "channel": event.get("channel"),
            "second": event.get("second"),
            "len": event.get("len"),
            "copied": event.get("copied"),
            "rssi": event.get("rssi"),
            "first_word_invalid": flag_is_true(event.get("first_word_invalid")),
            "unmasked_slot_count": valid_count,
            "mean_raw_amplitude": float(np.mean(raw_values[valid_amp])) if valid_count else math.nan,
            "mean_l2_normalized_amplitude": float(np.nanmean(l2_values)) if np.any(np.isfinite(l2_values)) else math.nan,
            "mean_rms_normalized_amplitude": float(np.nanmean(rms_values)) if np.any(np.isfinite(rms_values)) else math.nan,
            "l2_scale": float(run_data["rms_scale"][index] * math.sqrt(valid_count)) if valid_count and math.isfinite(run_data["rms_scale"][index]) else math.nan,
            "rms_scale": run_data["rms_scale"][index],
            "tail_bytes_hex": tail_hex,
        }
        for slot in range(slots):
            row[f"raw_amp_slot_{slot:02d}"] = raw_values[slot]
            row[f"rms_norm_amp_slot_{slot:02d}"] = rms_values[slot]
        rows.append(row)
    return fields, rows, selected


def summarize_rates_and_drops(summary: dict[str, Any], raw_records: int, analyzed_records: int) -> dict[str, Any]:
    duration = finite_or_none(summary.get("duration_after_armed_s"))
    final = summary.get("final_device_counters") if isinstance(summary.get("final_device_counters"), dict) else {}
    reported_rates = summary.get("rates_per_s") if isinstance(summary.get("rates_per_s"), dict) else {}
    callback_fields = ("prom_target_data", "csi_target_data", "csi_target_data_valid")
    callback_rates: dict[str, Any] = {}
    for field in callback_fields:
        count = int_or_none(final.get(field))
        if count is None:
            continue
        reported = finite_or_none(reported_rates.get(field))
        callback_rates[field] = {
            "callback_count_from_final_device_counters": count,
            "reported_rate_hz_from_summary": reported,
            "derived_rate_hz_from_final_count_and_duration": count / duration if duration and duration > 0 else None,
        }
    drops: dict[str, Any] = {}
    for scope_name, scope in (("final_device_counters", final), ("rates_per_s", reported_rates)):
        for key, value in scope.items():
            if "drop" in str(key).lower():
                drops[f"{scope_name}.{key}"] = value
    return {
        "duration_after_armed_s": duration,
        "callback_rates": callback_rates,
        "disk_rates": {
            "records_jsonl_count": raw_records,
            "records_jsonl_hz": raw_records / duration if duration and duration > 0 else None,
            "analysis_eligible_packet_count": analyzed_records,
            "analysis_eligible_hz": analyzed_records / duration if duration and duration > 0 else None,
            "reported_recording_rate_fields_from_summary": reported_rates,
            "elapsed_origin": "host duration_after_armed_s; divided counts may include host/device queue effects",
        },
        "drop_counters_from_summary_only": drops,
    }


def run_metrics(name: str, run_data: dict[str, Any], mode: str) -> dict[str, Any]:
    events = run_data["events"]
    groups = rate_groups(events)
    raw_allzero = np.mean(run_data["amplitudes"] == 0.0, axis=0) if len(events) else np.full(run_data["amplitudes"].shape[1], np.nan)
    unmasked_allzero = []
    for slot in range(run_data["amplitudes"].shape[1]):
        valid = ~run_data["masks"][:, slot]
        unmasked_allzero.append(float(np.mean(run_data["amplitudes"][valid, slot] == 0.0)) if np.any(valid) else None)
    stats = vector_statistics(run_data, np.arange(len(events), dtype=np.int64))
    return {
        "status": "analyzed" if events else "completed_empty",
        "analysis_packet_count": len(events),
        "rate_distribution": count_distribution(events, "rate"),
        "phy_rate_length_distribution": distribution_summary(events),
        "decoded_slot_count": int(run_data["amplitudes"].shape[1]),
        "physical_subcarrier_mapping_known": mode == "8",
        "first_word_invalid_packet_count": int(sum(flag_is_true(event.get("first_word_invalid")) for event in events)),
        "masked_sample_count_by_slot": np.sum(run_data["masks"], axis=0),
        "allzero_ratio_by_slot": raw_allzero,
        "unmasked_allzero_ratio_by_slot": unmasked_allzero,
        "allzero_candidate_slots": [int(i) for i, ratio in enumerate(raw_allzero) if math.isfinite(float(ratio)) and float(ratio) == 1.0],
        "zero_amplitude_definition": "decoded complex amplitude is exactly 0; candidate marking only, no slot is removed from primary analysis",
        "raw_amplitude": stats["raw"],
        "rms_normalized_amplitude": stats["rms"],
        "l2_normalized_amplitude": stats["l2"],
        "saturation": run_data["saturation"],
        "tail_two_bytes": tail_distribution(run_data["tail_bytes"]),
        "timestamp": run_data["timestamp_info"],
        "mean_amplitude_timeseries_count": len(events),
    }


def unit_vector(values: np.ndarray, allowed: np.ndarray | None = None) -> tuple[np.ndarray | None, np.ndarray]:
    valid = np.isfinite(values)
    if allowed is not None:
        valid &= allowed
    selected = values[valid]
    norm = float(np.linalg.norm(selected)) if selected.size else 0.0
    if not selected.size or norm <= 0:
        return None, valid
    result = np.full_like(values, np.nan, dtype=np.float64)
    result[valid] = selected / norm
    return result, valid


def vector_comparison(
    reference: dict[str, Any], other: dict[str, Any], ref_indices: np.ndarray, other_indices: np.ndarray,
    excluded_slots: set[int] | None = None,
) -> dict[str, Any]:
    ref_mean = mean_rows(reference["rms_norm"], ref_indices)
    other_mean = mean_rows(other["rms_norm"], other_indices)
    shared = np.isfinite(ref_mean) & np.isfinite(other_mean)
    excluded = excluded_slots or set()
    for slot in excluded:
        if 0 <= slot < len(shared):
            shared[slot] = False
    ref_unit, ref_valid = unit_vector(ref_mean, shared)
    other_unit, other_valid = unit_vector(other_mean, shared)
    valid = ref_valid & other_valid
    common_count = int(np.count_nonzero(valid))
    if ref_unit is None or other_unit is None:
        pearson = None
        l2_distance = None
        reason = "no comparable nonzero mean vector"
    else:
        x = ref_unit[valid]
        y = other_unit[valid]
        pearson = float(np.corrcoef(x, y)[0, 1]) if len(x) >= 2 and np.std(x) > 0 and np.std(y) > 0 else None
        l2_distance = float(np.linalg.norm(x - y))
        reason = None if pearson is not None else "Pearson correlation unavailable (fewer than two slots or a constant vector)"
    return {
        "reference_packet_count": int(len(ref_indices)),
        "other_packet_count": int(len(other_indices)),
        "common_unmasked_slot_count": common_count,
        "pearson_mean_vector": pearson,
        "normalized_l2_distance": l2_distance,
        "normalized_l2_definition": "Euclidean distance between each run's common-slot mean RMS-normalized amplitude vector after unit-L2 normalization",
        "excluded_slots": sorted(excluded),
        "unavailable_reason": reason,
    }


def allzero_slot_set(run_data: dict[str, Any], indices: np.ndarray) -> set[int]:
    if len(indices) == 0:
        return set()
    ratios = np.mean(run_data["amplitudes"][indices] == 0.0, axis=0)
    return {int(i) for i, ratio in enumerate(ratios) if float(ratio) == 1.0}


def pairwise_comparison(reference_name: str, other_name: str, datasets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if reference_name not in datasets:
        return {"status": "pending", "pending_reason": "reference run unavailable"}
    if other_name not in datasets:
        return {"status": "pending", "pending_reason": "comparison run unavailable"}
    reference = datasets[reference_name]
    other = datasets[other_name]
    ref_groups = rate_groups(reference["events"])
    other_groups = rate_groups(other["events"])
    common_rates = sorted(set(ref_groups) & set(other_groups))
    per_rate: dict[str, Any] = {}
    for key in common_rates:
        ref_idx = ref_groups[key]
        other_idx = other_groups[key]
        base = vector_comparison(reference, other, ref_idx, other_idx)
        zero_slots = allzero_slot_set(reference, ref_idx) | allzero_slot_set(other, other_idx)
        sensitivity = vector_comparison(reference, other, ref_idx, other_idx, zero_slots)
        per_rate[key] = {
            "rate_value": json.loads(key),
            "comparison": base,
            "optional_allzero_slot_sensitivity": {
                "candidate_slots_excluded": sorted(zero_slots),
                "comparison": sensitivity,
                "note": "optional diagnostic only; primary comparison retains every slot not explicitly masked by first_word_invalid/DC rules",
            },
        }
    ref_all = np.arange(len(reference["events"]), dtype=np.int64)
    other_all = np.arange(len(other["events"]), dtype=np.int64)
    return {
        "status": "compared" if common_rates else "no_common_rate",
        "reference": reference_name,
        "other": other_name,
        "common_rate_strata": per_rate,
        "common_rate_count": len(common_rates),
        "pooled_all_rates_diagnostic_only": {
            **vector_comparison(reference, other, ref_all, other_all),
            "warning": "pooled diagnostic can mix rate values; use common_rate_strata for the primary comparison",
        },
    }


def half_stability(name: str, run_data: dict[str, Any]) -> dict[str, Any]:
    groups = rate_groups(run_data["events"])
    by_rate: dict[str, Any] = {}
    for key, indices in sorted(groups.items()):
        midpoint = len(indices) // 2
        first = indices[:midpoint]
        second = indices[midpoint:]
        base = vector_comparison(run_data, run_data, first, second)
        zero_slots = allzero_slot_set(run_data, first) | allzero_slot_set(run_data, second)
        sensitivity = vector_comparison(run_data, run_data, first, second, zero_slots)
        by_rate[key] = {
            "rate_value": json.loads(key),
            "first_half_packet_count": int(len(first)),
            "second_half_packet_count": int(len(second)),
            "comparison": base,
            "optional_allzero_slot_sensitivity": {
                "candidate_slots_excluded": sorted(zero_slots),
                "comparison": sensitivity,
                "note": "optional diagnostic only; primary stability metric keeps all decoded slots except explicit masks",
            },
        }
    return {
        "status": "analyzed" if len(run_data["events"]) else "insufficient_data",
        "split": "first and second chronological halves within each rate stratum",
        "by_common_rate": by_rate,
        "pooled_all_rates_diagnostic_only": {
            **vector_comparison(
                run_data, run_data,
                np.arange(0, len(run_data["events"]) // 2, dtype=np.int64),
                np.arange(len(run_data["events"]) // 2, len(run_data["events"]), dtype=np.int64),
            ),
            "warning": "pooled diagnostic can mix rate values; use by_common_rate for the primary comparison",
        },
    }


def plot_outputs(root: Path, mode: str, run_data: dict[str, dict[str, Any]], run_summaries: dict[str, dict[str, Any]]) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure_dir = root / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []
    available = [name for name in RUN_NAMES if name in run_data and len(run_data[name]["events"])]
    colors = dict(zip(RUN_NAMES, plt.cm.tab10.colors[:len(RUN_NAMES)]))
    def display(name):
        invalid=run_summaries.get(name,{}).get("run_quality_metadata",{}).get("exclude_from_physical_comparisons",False)
        return name+" [INVALID CONTROL: device moved]" if invalid else name

    def save(fig: Any, stem: str) -> None:
        fig.tight_layout()
        png = figure_dir / (stem + ".png")
        svg = figure_dir / (stem + ".svg")
        fig.savefig(png, dpi=160)
        fig.savefig(svg)
        plt.close(fig)
        generated.extend((str(png), str(svg)))

    # 1. RSSI versus the unwrapped ESP RX timestamp axis.
    fig, ax = plt.subplots(figsize=(10, 5.4))
    plotted = False
    for name in available:
        data = run_data[name]
        rssi = np.asarray([finite_or_none(e.get("rssi")) if finite_or_none(e.get("rssi")) is not None else np.nan for e in data["events"]])
        ok = np.isfinite(data["elapsed_s"]) & np.isfinite(rssi)
        if np.any(ok):
            ax.scatter(data["elapsed_s"][ok], rssi[ok], s=8, alpha=0.55, color=colors[name], label=display(name))
            plotted = True
    if plotted:
        ax.set_xlabel("Elapsed time from first analyzed packet (s; unwrapped ESP RX32 timestamp)")
        ax.set_ylabel("RSSI (dBm)")
        ax.legend()
    else:
        ax.text(0.5, 0.5, "No completed run with RSSI and timestamp data", ha="center", va="center", transform=ax.transAxes)
    ax.set_title("RSSI versus packet time; packet spacing is irregular and is not resampled")
    ax.grid(True, alpha=0.25)
    save(fig, "01_rssi_vs_time")

    # 2. Per-packet mean amplitude before and after per-packet scale normalization.
    fig, axes = plt.subplots(2, 1, figsize=(10, 7.3), sharex=True)
    for name in available:
        data = run_data[name]
        mean_raw = np.nanmean(data["raw_amp"], axis=1)
        mean_norm = np.nanmean(data["rms_norm"], axis=1)
        ok = np.isfinite(data["elapsed_s"])
        axes[0].plot(data["elapsed_s"][ok], mean_raw[ok], ".", ms=3, alpha=0.55, color=colors[name], label=display(name))
        axes[1].plot(data["elapsed_s"][ok], mean_norm[ok], ".", ms=3, alpha=0.55, color=colors[name], label=display(name))
    axes[0].set_ylabel("Mean raw amplitude (I/Q units)")
    axes[1].set_ylabel("Mean per-packet RMS-normalized amplitude")
    axes[1].set_xlabel("Elapsed time from first analyzed packet (s)")
    for ax in axes:
        ax.grid(True, alpha=0.25)
        if available:
            ax.legend()
        else:
            ax.text(0.5, 0.5, "Completed run data pending", ha="center", va="center", transform=ax.transAxes)
    fig.suptitle("Per-packet mean amplitude; normalization reduces overall scale variation but is not AGC calibration")
    save(fig, "02_packet_mean_amplitude")

    # 3. Prespecified six evenly spaced slots, separated by run for readability.
    fig, axes = plt.subplots(len(RUN_NAMES), 1, figsize=(10, 2.5*len(RUN_NAMES)), sharex=True, squeeze=False)
    axes=axes[:,0]
    for ax, name in zip(axes, RUN_NAMES):
        if name not in run_data:
            ax.text(.5,.5,"Completed run pending",ha="center",transform=ax.transAxes)
            continue
        data = run_data[name]
        for slot in selected_six_slots(data):
            values = data["rms_norm"][:,slot]
            ok = np.isfinite(data["elapsed_s"]) & np.isfinite(values)
            ax.plot(data["elapsed_s"][ok], values[ok], ".-",ms=2.5,lw=.7,label=slot_label(slot,mode))
        ax.set_title(display(name)); ax.set_ylabel("RMS-norm amplitude")
        ax.legend(ncol=3,fontsize=7); ax.grid(True,alpha=.25)
    axes[-1].set_xlabel("Elapsed time from first analyzed packet (s); no resampling")
    fig.suptitle("Six uniformly selected packed slots; physical carrier mapping unknown in 12-bit mode")
    save(fig,"03_six_slot_timeseries")

    # 4. Rate-stratified per-run mean response. 12-bit slots are not called carriers.
    ref_groups = rate_groups(run_data["static1"]["events"]) if "static1" in run_data else {}
    rate_keys: set[str] = set()
    if ref_groups:
        for name in RUN_NAMES:
            if name == "static1" or name not in run_data:
                continue
            rate_keys.update(set(ref_groups) & set(rate_groups(run_data[name]["events"])))
    if len(rate_keys) <= 1:
        panels = [next(iter(rate_keys))] if rate_keys else [None]
    else:
        panels = sorted(rate_keys)
    columns = min(2, max(1, len(panels)))
    rows_n = int(math.ceil(len(panels) / columns))
    fig, axes = plt.subplots(rows_n, columns, figsize=(7.5 * columns, 4.6 * rows_n), squeeze=False)
    for panel_index, rate_key in enumerate(panels):
        ax = axes.flat[panel_index]
        for name in available:
            data = run_data[name]
            indices = rate_groups(data["events"]).get(rate_key) if rate_key is not None else np.arange(len(data["events"]))
            if indices is None or len(indices) == 0:
                continue
            mean = mean_rows(data["rms_norm"], indices)
            if mode == "8":
                x = np.asarray(list(range(0, 27)) + list(range(-26, 0)))
                order = np.argsort(x)
                ax.plot(x[order], mean[order], marker=".", lw=1.2, color=colors[name], label=display(name))
                ax.set_xlabel("Subcarrier index k")
            else:
                x = np.arange(len(mean))
                ax.plot(x, mean, marker=".", lw=1.2, color=colors[name], label=display(name))
                ax.set_xlabel("Packed complex slot (physical carrier mapping unknown)")
            if rate_key is not None:
                ax.set_title("rate=" + rate_key)
            else:
                ax.set_title("Pooled rates; diagnostic only (no common rate stratum)")
            ax.set_ylabel("Mean per-packet RMS-normalized amplitude")
            ax.grid(True, alpha=0.25)
            if available:
                ax.legend()
        if not available:
            ax.text(0.5, 0.5, "Completed run data pending", ha="center", va="center", transform=ax.transAxes)
    for panel_index in range(len(panels), rows_n * columns):
        axes.flat[panel_index].set_visible(False)
    fig.suptitle("Mean normalized response by rate stratum; no absolute AGC calibration")
    save(fig, "04_mean_response_by_rate")

    fig, ax = plt.subplots(figsize=(10,5.4))
    for name in available:
        data = run_data[name]
        mean = mean_rows(data["raw_amp"],np.arange(len(data["events"])))
        ax.plot(np.arange(len(mean)),mean,marker=".",label=display(name))
    ax.set_xlabel("Packed complex slot (12-bit physical carrier mapping unknown)")
    ax.set_ylabel("Mean raw amplitude (SDK units)")
    ax.set_title("Raw mean response; inspect PHY/rate strata before interpretation")
    if available: ax.legend()
    ax.grid(True,alpha=.25)
    save(fig,"04b_raw_mean_response")

    # 5. Per-slot raw and normalized time variance. Zero candidates remain in view.
    fig, axes = plt.subplots(2, 1, figsize=(10, 7.6), sharex=True)
    for name in available:
        data = run_data[name]
        raw_stats = column_stats(data["raw_amp"], data["masks"])
        norm_stats = column_stats(data["rms_norm"], data["masks"])
        if mode == "8":
            carriers = np.asarray(list(range(0, 27)) + list(range(-26, 0)))
            order = np.argsort(carriers)
            x = carriers[order]
            raw_y = raw_stats["variance"][order]
            norm_y = norm_stats["variance"][order]
        else:
            x = np.arange(data["amplitudes"].shape[1])
            raw_y = raw_stats["variance"]
            norm_y = norm_stats["variance"]
        axes[0].plot(x, raw_y, marker=".", lw=1.1, color=colors[name], label=display(name))
        axes[1].plot(x, norm_y, marker=".", lw=1.1, color=colors[name], label=display(name))
    axes[0].set_ylabel("Raw amplitude variance (units²)")
    axes[1].set_ylabel("RMS-normalized amplitude variance")
    axes[1].set_xlabel("Subcarrier index k" if mode == "8" else "Packed complex slot (physical carrier mapping unknown)")
    for ax in axes:
        ax.grid(True, alpha=0.25)
        if available:
            ax.legend()
        else:
            ax.text(0.5, 0.5, "Completed run data pending", ha="center", va="center", transform=ax.transAxes)
    fig.suptitle("Per-slot time variance; exact all-zero candidate slots are retained in the primary view")
    save(fig, "05_slot_time_variance")
    valid_names=[name for name in available if not run_summaries.get(name,{}).get("run_quality_metadata",{}).get("exclude_from_physical_comparisons",False)]
    fig,axes=plt.subplots(2,1,figsize=(11,7.2),sharex=True)
    raw_vars=[];norm_vars=[]
    for name in valid_names:
        data=run_data[name]
        raw_vars.append(float(np.nanmean(column_stats(data["raw_amp"],data["masks"])["variance"])))
        norm_vars.append(float(np.nanmean(column_stats(data["rms_norm"],data["masks"])["variance"])))
    axes[0].bar(valid_names,raw_vars);axes[1].bar(valid_names,norm_vars)
    axes[0].set_ylabel("Mean raw slot variance");axes[1].set_ylabel("Mean RMS-normalized slot variance")
    axes[1].tick_params(axis="x",rotation=20)
    fig.suptitle("Valid condition controls only; contaminated Run A excluded, no fixed pass threshold")
    save(fig,"06_valid_controls_variance")
    return generated


def slot_label(slot: int, mode: str) -> str:
    if mode == "12":
        return f"slot{slot}"
    carrier = list(range(0, 27)) + list(range(-26, 0))
    return f"k{carrier[slot]}"


def write_run_csvs(root: Path, name: str, run_data: dict[str, Any] | None, mode: str) -> dict[str, Any]:
    vector_path = root / "analysis" / f"vectors_{name}.csv"
    timeseries_path = root / "analysis" / f"timeseries_{name}.csv"
    if run_data is None:
        write_csv(vector_path, VECTOR_FIELDS, [])
        write_csv(timeseries_path, ("packet_index",), [])
        return {"vectors_csv": str(vector_path), "timeseries_csv": str(timeseries_path), "selected_six_slots": []}
    vector_rows = build_vector_rows(name, run_data, mode)
    ts_fields, ts_rows, selected = build_timeseries_rows(run_data, mode)
    write_csv(vector_path, VECTOR_FIELDS, vector_rows)
    write_csv(timeseries_path, ts_fields, ts_rows)
    return {
        "vectors_csv": str(vector_path),
        "timeseries_csv": str(timeseries_path),
        "selected_six_slots": selected,
        "selected_six_slot_labels": [slot_label(slot, mode) for slot in selected],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze completed offline ESP32-C5 CSI physical experiment runs")
    parser.add_argument("--root", required=True, type=Path, help="result directory containing static1/blocked/static2/motion/static3")
    parser.add_argument("--mac", required=True, help="required source MAC to retain, supply your actual locally verified target address")
    parser.add_argument("--lltf-mode", required=True, choices=("12", "8"), help="decoder mode from the firmware's lltf_bit_mode setting: 0=12, 1=8")
    parser.add_argument("--reference",default="static2",help="uncontaminated reference run, default static2")
    parser.add_argument("--runs", default=",".join(RUN_NAMES),help="comma-separated independent run directory names; default is the original five")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global RUN_NAMES
    args = parse_args(argv)
    requested=tuple(x.strip() for x in args.runs.split(",") if x.strip())
    if not requested or len(requested)>10 or any(not re.fullmatch(r"[a-zA-Z0-9_-]+",x) for x in requested) or len(set(requested))!=len(requested):
        raise SystemExit("--runs must contain 1..10 unique plain directory names")
    RUN_NAMES=requested
    mac = args.mac.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac):
        raise SystemExit("--mac must be a six-octet colon-separated MAC address")
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise SystemExit("--root must be an existing completed-result parent directory: " + str(root))

    run_summaries: dict[str, dict[str, Any]] = {}
    datasets: dict[str, dict[str, Any]] = {}
    csv_outputs: dict[str, Any] = {}
    decoded_runs: dict[str, dict[str, Any]] = {}
    mode = args.lltf_mode
    for name in RUN_NAMES:
        events, summary, state = load_completed_run(root / name)
        if events is None or summary is None:
            run_summaries[name] = state
            csv_outputs[name] = write_run_csvs(root, name, None, mode)
            continue

        metadata_path=root/name/"run_metadata.json"
        quality_metadata=json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        state["run_quality_metadata"]=quality_metadata
        eligible, filter_counts = get_filter_pipeline(events, mac)
        state.update({
            "raw_records_json_objects": len(events),
            "source_target_mac": mac,
            "filter_counts_sequential": filter_counts,
            "raw_distributions": distribution_summary(events),
            "summary_rates_and_drops": summarize_rates_and_drops(summary, len(events), len(eligible)),
            "summary_classification_preserved_as_metadata_only": summary.get("classification"),
        })
        run_summaries[name] = state
        if eligible:
            data = make_run_data(eligible, mode)
            datasets[name] = data
            decoded_runs[name] = run_metrics(name, data, mode)
            run_summaries[name]["analysis"] = decoded_runs[name]
        else:
            # Completed input with no records passing the declared filters is data, not a fabricated empty run.
            run_summaries[name]["analysis"] = {
                "status": "no_eligible_packets",
                "analysis_packet_count": 0,
                "note": "all available records failed one or more explicit filters; raw records remain unchanged",
                "decoder": decoder_description(mode),
            }
        csv_outputs[name] = write_run_csvs(root, name, datasets.get(name), mode)

    comparison_datasets={name:data for name,data in datasets.items() if not run_summaries[name].get("run_quality_metadata",{}).get("exclude_from_physical_comparisons",False)}
    reference=args.reference
    if reference not in comparison_datasets:
        raise SystemExit("reference run must exist and must not be excluded as a physical control")
    comparisons={name:pairwise_comparison(reference,name,comparison_datasets) for name in RUN_NAMES if name!=reference}
    all_pairs={f"{a}_vs_{b}":pairwise_comparison(a,b,comparison_datasets) for i,a in enumerate(RUN_NAMES) for b in RUN_NAMES[i+1:]}
    invalid_names=set(datasets)-set(comparison_datasets)
    for name in invalid_names:
        comparisons[name]={"status":"invalid_control_excluded","reason":run_summaries[name].get("run_quality_metadata",{}).get("reason")}
    for key in list(all_pairs):
        if any(key.startswith(n+"_vs_") or key.endswith("_vs_"+n) for n in invalid_names):
            all_pairs[key]={"status":"invalid_control_excluded","reason":"run metadata records physical interference; no physical comparison computed"}
    for name in datasets:
        if name not in comparison_datasets:
            run_summaries[name]["physical_control_status"]="invalid: retained as diagnostic only, excluded from physical comparisons"
    stability={name:half_stability(name,comparison_datasets[name]) for name in comparison_datasets if name.startswith("static") or name.startswith("recovery")}

    generated_figures = plot_outputs(root, mode, datasets, run_summaries)
    summary_out = {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_root": str(root),
        "requested_source_mac": mac,
        "lltf_mode": mode,
        "decoder": decoder_description(mode),
        "primary_scope": "offline analysis only; no automatic physical validation pass/fail or fixed percentage threshold",
        "runs": run_summaries,
        "csv_outputs": csv_outputs,
        "reference_run": reference,
        "reference_vs_other_runs": comparisons,
        "all_pairwise_comparisons": all_pairs,
        "static_within_run_front_back_stability": stability,
        "figures": generated_figures,
        "interpretation_limits": [
            "All input formats and lengths are counted; only source-matched uplink Data, format=1, second=0, len=106, valid=1, rx_state=0, copied=len, correct nonempty hex, and known first_word_invalid are decoded.",
            "No AGC calibration guarantee is available. Raw amplitude is an SDK buffer magnitude; per-packet L2/RMS normalization reduces overall scale variation but does not calibrate AGC or establish absolute channel gain.",
            "12-bit mode reports packed complex slots only. It does not infer a DC slot, carrier index, or complete frequency axis; the final two bytes are preserved and counted as uninterpreted.",
            "Exact all-zero slots are marked as candidates and remain in primary summaries/figures. Optional sensitivity metrics exclude only candidate slots and are labeled separately.",
            "Unwrapped timestamps are relative to the first analyzed packet; packet times are irregular and are not resampled.",
            "Callback rates and device drop counters come from summary.json. Disk and analysis rates are host record counts divided by summary duration and do not claim RF loss attribution.",
            "Missing or incomplete run pairs remain pending; records are not read until both records.jsonl and summary.json exist.",
        ],
    }
    output_path = root / "analysis" / "analysis_summary.json"
    output_path.write_text(json.dumps(json_safe(summary_out), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "analysis_summary": str(output_path),
        "lltf_mode": mode,
        "run_status": {name: run_summaries[name].get("status") for name in RUN_NAMES},
        "analyzed_packets": {name: run_summaries[name].get("analysis", {}).get("analysis_packet_count", 0) for name in RUN_NAMES},
        "figures": generated_figures,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
