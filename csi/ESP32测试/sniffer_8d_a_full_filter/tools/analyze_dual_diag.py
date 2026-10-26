"""Create private host-side funnel, timeline, handshake and CSI_DATA summaries."""
import argparse
import collections
import json
from pathlib import Path

from dual_diag import exact_pair_direction, validate_timeline_rows
from wire8c import assemble_api_parts, parse_header
from wpa2_gate8c import classify_record, convert, handshake, read_stream


def analyze_capture(capture, target, ap):
    capture = Path(capture)
    private_dir = capture / 'analysis_private'
    converted = convert(capture, private_dir, target.lower(), ap.lower(), live=False)
    rows, transport = read_stream(capture, live=False)
    frame_rows = [r for r in rows if r['event'] == 'FRAME']
    csi_rows = [r for r in rows if r['event'] == 'CSI_DATA']
    timeline_rows = [r for r in rows if r['event'] == 'TIMELINE']
    buckets = validate_timeline_rows(timeline_rows)

    messages = {n: [] for n in range(1, 5)}
    parser_rejects = collections.Counter()
    eapol_records = []
    for row in rows:
        if row['event'] not in ('FRAME', 'CSI_DATA'):
            continue
        try:
            classified, _ = classify_record(row, target.lower(), ap.lower())
        except (ValueError, KeyError, TypeError) as exc:
            parser_rejects[f"{row['event']}:{exc}"] += 1
            continue
        if classified['message'] in messages:
            n = classified['message']
            item = dict(message=n, source_event=row['event'],
                        direction=classified['direction'],
                        record_serial=row['record_serial'],
                        rx_seq=row.get('rx_seq'),
                        key_info=classified['key_info'],
                        replay_counter=classified['replay_counter'],
                        same_record_csi=classified['same_record_csi'],
                        csi_valid=classified['csi_valid'])
            messages[n].append(item)
            eapol_records.append(classified)

    csi_stats = dict(total=len(csi_rows), protected=0, clear=0,
                     jetson_to_ap=0, ap_to_jetson=0, other_direction=0,
                     valid_csi=0, complete_payload=0, incomplete_payload=0,
                     payload_le256=0, payload_gt256=0, malformed=0)
    for row in csi_rows:
        try:
            raw = assemble_api_parts(row)
            header = parse_header(raw)
        except (ValueError, KeyError, TypeError):
            csi_stats['malformed'] += 1
            continue
        csi_stats['protected' if header['protected'] else 'clear'] += 1
        direction = exact_pair_direction(header, target.lower(), ap.lower())
        if direction == 'jetson_to_ap':
            csi_stats['jetson_to_ap'] += 1
        elif direction == 'ap_to_jetson':
            csi_stats['ap_to_jetson'] += 1
        else:
            csi_stats['other_direction'] += 1
        if row.get('csi_valid'):
            csi_stats['valid_csi'] += 1
        if row.get('payload_complete'):
            csi_stats['complete_payload'] += 1
        else:
            csi_stats['incomplete_payload'] += 1
        if row.get('payload_len', 0) <= 256:
            csi_stats['payload_le256'] += 1
        else:
            csi_stats['payload_gt256'] += 1

    coherent = handshake(eapol_records)
    summary_file = capture / 'summary.json'
    capture_summary = json.loads(summary_file.read_text(encoding='utf-8')) if summary_file.exists() else {}
    counters = capture_summary.get('counters', {})
    transport_errors = capture_summary.get('transport_errors', {})
    public_safe_messages = {str(n): [dict(item) for item in values]
                            for n, values in messages.items()}
    result = dict(
        firmware=capture_summary.get('firmware'),
        mode=capture_summary.get('mode'),
        capture_duration_s=capture_summary.get('duration_s'),
        record_counts=dict(FRAME=len(frame_rows), CSI_DATA=len(csi_rows), TIMELINE=len(timeline_rows)),
        dual_counters={k: v for k, v in counters.items() if k.startswith(('prom_', 'csi_', 'raw_', 'write_'))
                       or k in ('queue_drop', 'diag_pair_seen', 'diag_candidate_enqueued')},
        timeline=buckets,
        eapol_messages=public_safe_messages,
        handshake=dict(messages=coherent['messages'],
                       complete_four_way=coherent['complete_four_way'],
                       coherent_record_serials=coherent['coherent_record_serials'],
                       mic_verification='not performed; EAPOL-Key classification only'),
        csi_data=csi_stats,
        parser_reject_counts=dict(sorted(parser_rejects.items())),
        transport=transport,
        transport_errors=transport_errors,
        private_pcap=str(private_dir / 'combined_private.pcap'))

    summary_path = capture / 'dual_diag_summary.json'
    summary_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    report_path = capture / 'dual_diag_report.md'
    report_path.write_text(render_report(result), encoding='utf-8')
    return result


def render_report(result):
    counters = result['dual_counters']
    prom_funnel = (
        ('target-related Data', 'prom_target_related'), ('exact pair', 'prom_pair'),
        ('clear pair', 'prom_clear'), ('LLC/SNAP', 'prom_llc_snap'),
        ('EtherType 0x888e', 'prom_ethertype_888e'),
        ('EAPOL candidates', 'prom_eapol_candidate'), ('RAW enqueued', 'prom_raw_enqueued'),
        ('RAW output', 'prom_raw_output'))
    csi_funnel = (
        ('exact pair CSI', 'csi_pair'), ('valid CSI', 'csi_valid'),
        ('clear', 'csi_clear'), ('Protected', 'csi_protected'),
        ('payload available', 'csi_payload_available'), ('payload <=256 B', 'csi_len_le256'),
        ('CSI_DATA enqueued', 'csi_data_enqueued'), ('CSI_DATA output', 'csi_data_output'))
    lines = [
        '# HANDSHAKE_DUAL_DIAG 私有离线分析', '',
        f"- Firmware: `{result.get('firmware')}`; mode: `{result.get('mode')}`; duration: {result.get('capture_duration_s')} s.",
        f"- Records: FRAME={result['record_counts']['FRAME']}, CSI_DATA={result['record_counts']['CSI_DATA']}, TIMELINE={result['record_counts']['TIMELINE']}.",
        '- 该文件与同目录的 `analysis_private/` 只留在本机；其中 PCAP/握手解析属于私有证据。', '',
        '## Promiscuous 过滤漏斗', '', '| 阶段 | 计数 |', '|---|---:|']
    lines += [f'| {label} | {counters.get(key, 0)} |' for label, key in prom_funnel]
    lines += ['', '## CSI callback 原子记录漏斗', '', '| 阶段 | 计数 |', '|---|---:|']
    lines += [f'| {label} | {counters.get(key, 0)} |' for label, key in csi_funnel]
    lines += ['', '## EAPOL-Key 消息来源', '', '| 消息 | FRAME | CSI_DATA | 记录明细 |', '|---|---:|---:|---|']
    for n in range(1, 5):
        entries = result['eapol_messages'][str(n)]
        nf = sum(x['source_event'] == 'FRAME' for x in entries)
        nc = sum(x['source_event'] == 'CSI_DATA' for x in entries)
        detail = '; '.join(f"{x['direction']} serial={x['record_serial']} rx_seq={x['rx_seq']} CSI有效={x['csi_valid']}"
                           for x in entries) or '未识别'
        lines.append(f'| M{n} | {nf} | {nc} | {detail} |')
    hs = result['handshake']
    lines += ['', f"- Coherent M1–M4 sequence: **{hs['complete_four_way']}** (classification only; MIC verification not performed).",
              '', '## CSI_DATA 概况', '', '| 指标 | 计数 |', '|---|---:|']
    lines += [f'| {k} | {v} |' for k, v in result['csi_data'].items()]
    lines += ['', '## Timeline buckets', '',
              '| bucket | ESP timer start–end (us) | span (us) | prom pair | prom EAPOL | raw out | CSI pair | CSI protected | CSI_DATA out |',
              '|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for b in result['timeline']:
        c = b['counters']
        lines.append(f"| {b['bucket_id']} | {b['start_us']}–{b['end_us']} | {b['actual_span_us']} | "
                     f"{c.get('prom_pair', 0)} | {c.get('prom_eapol_candidate', 0)} | {c.get('prom_raw_output', 0)} | "
                     f"{c.get('csi_pair', 0)} | {c.get('csi_protected', 0)} | {c.get('csi_data_output', 0)} |")
    lines += ['', '## 丢弃、截断与传输状态', '', '```json',
              json.dumps(dict(counters=result['dual_counters'],
                              transport_errors=result['transport_errors'],
                              transport=result['transport']), indent=2),
              '```', '', '## 边界', '',
              '- 本分析不解密 Protected payload，也不从密文中推测 UDP 或 packet_id。',
              '- 清晰的 EAPOL-Key 分类不等于 MIC 验证或 WPA2 解密。',
              '- `analysis_private/combined_private.pcap` 包含捕获到的目标帧；不得公开或提交。', '']
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description='Offline HANDSHAKE_DUAL_DIAG stream analysis')
    p.add_argument('--capture', type=Path, required=True)
    p.add_argument('--target', required=True)
    p.add_argument('--ap', required=True)
    args = p.parse_args()
    result = analyze_capture(args.capture, args.target, args.ap)
    print(json.dumps(dict(records=result['record_counts'], handshake=result['handshake'],
                          csi_data=result['csi_data'], report=str(args.capture / 'dual_diag_report.md')),
                     indent=2))


if __name__ == '__main__':
    main()
