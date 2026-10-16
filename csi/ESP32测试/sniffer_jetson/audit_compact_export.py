"""Audit saved compact UART trials; never operates hardware."""
import argparse
import json
from pathlib import Path
from analyze_phy_control import audit


def evaluate(capture, target, active=False):
    result = audit(capture, target)
    host = json.loads((capture/'summary.json').read_text(encoding='utf-8'))
    f = result['final_device_counters']
    transport = host['transport_audit']
    result.update(capture_scope='active UDP window' if active else 'passive HT sanity; no probe sender',
                  sender={'status': 'see endpoint logs' if active else 'not started'},
                  receiver={'status': 'see endpoint logs' if active else 'not started'},
                  transport_audit=transport)
    checks = {
        'ready_and_final': host['armed'] and host['stop_final_received'],
        'queue_drop_zero': f['frame_drop'] == f['csi_drop'] == 0,
        'serial_write_errors_zero': f['serial_write_errors'] == 0,
        'parse_errors_zero': host['event_counts'].get('json_parse_error', 0) == 0,
        'empty_truncated_zero': f['csi_empty'] == f['csi_truncated'] == 0,
        'record_sequence_complete': transport['sequence_contiguous_from_one'],
        'device_output_equals_host': transport['output_equals_host'],
        'queue_fully_drained': transport['enqueued_equals_output'],
        'callback_queue_reconciled': f['prom_target_data'] == f['frame_enqueued']+f['frame_target_drop'] and f['csi_target_data_valid'] == f['csi_enqueued']+f['csi_target_drop'],
        'valid_source_and_ht_pairs': result['sanity_reception_validity_passed'] and result['one_to_one_both_ht_metadata_keys'] > 0,
    }
    result['quality_checks'] = checks
    result['export_quality_passed'] = all(checks.values())
    result['sanity_export_quality_passed'] = result['export_quality_passed']
    result['classification'] = 'HT_Data_and_valid_HT_CSI_observed' if checks['valid_source_and_ht_pairs'] else 'HT_evidence_insufficient'
    result['full_trial_status'] = 'active_window_export_passed' if active and all(checks.values()) else ('passive_sanity_passed' if all(checks.values()) else 'export_quality_gate_failed')
    result['limits'] = ['No wireless capture-rate denominator is available.', 'CSI and FRAME counts include background traffic.', 'Metadata pairs do not identify encrypted business packet IDs.', 'Raw HT CSI bytes preserved; no IQ layout interpretation applied.']
    result['event_wire_bytes_per_s'] = f['serial_bytes']/result['duration_s']
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture', type=Path, required=True)
    p.add_argument('--target-mac', required=True)
    p.add_argument('--active', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = evaluate(a.capture, a.target_mac, a.active)
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: result[k] for k in ('target_data_frame_records', 'target_csi_records', 'one_to_one_both_ht_metadata_keys', 'frame_drop', 'csi_drop', 'export_quality_passed', 'quality_checks')}))
