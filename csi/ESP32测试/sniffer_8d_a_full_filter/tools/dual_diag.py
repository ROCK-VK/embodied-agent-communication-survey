"""Offline reference model and report helpers for HANDSHAKE_DUAL_DIAG.

The ESP firmware remains the capture implementation. These functions provide
deterministic host-side checks for its documented gates and analyze saved UART
streams without controlling a network interface.
"""
from collections import Counter, defaultdict

from wire8c import assemble_api_parts, parse_header

CANDIDATE_MAX = 256
RAW_CAPACITY = 2048
TIMELINE_BUCKET_US = 200_000


def exact_pair_direction(header, target, ap):
    """Return the infrastructure Data direction only for the exact STA/AP pair."""
    target = target.lower()
    ap = ap.lower()
    if header['to_ds'] == 1 and header['from_ds'] == 0:
        if header['address1'] == ap and header['address2'] == target:
            return 'jetson_to_ap'
    if header['to_ds'] == 0 and header['from_ds'] == 1:
        if header['address1'] == target and header['address2'] == ap:
            return 'ap_to_jetson'
    return None


def clear_llc_info(raw, header):
    """Read clear LLC/SNAP metadata; return false values for protected bodies."""
    if header['protected'] or header['fragment'] or header['more_fragments'] or header['amsdu']:
        return dict(llc_snap=False, ether_type=None)
    body = raw[header['header_len']:]
    if len(body) < 6 or body[:6] != bytes.fromhex('aaaa03000000'):
        return dict(llc_snap=False, ether_type=None)
    if len(body) < 8:
        return dict(llc_snap=True, ether_type=None)
    return dict(llc_snap=True, ether_type=int.from_bytes(body[6:8], 'big'))


def promisc_candidate(raw, target, ap):
    """Model the DUAL promiscuous gate; only clear EAPOL pair MPDUs pass."""
    try:
        header = parse_header(raw)
    except ValueError as exc:
        return dict(accepted=False, reason=f'malformed:{exc}')
    direction = exact_pair_direction(header, target, ap)
    if not direction:
        return dict(accepted=False, reason='not_exact_pair', header=header)
    if header['protected']:
        return dict(accepted=False, reason='protected', direction=direction, header=header)
    if header['fragment'] or header['more_fragments'] or header['amsdu']:
        return dict(accepted=False, reason='incomplete_or_amsdu', direction=direction, header=header)
    llc = clear_llc_info(raw, header)
    is_eapol = llc['llc_snap'] and llc['ether_type'] == 0x888e
    if not is_eapol:
        return dict(accepted=False, reason='not_eapol', direction=direction,
                    header=header, **llc)
    if len(raw) > RAW_CAPACITY:
        return dict(accepted=False, reason='raw_capacity', direction=direction,
                    header=header, **llc)
    return dict(accepted=True, reason='eapol_candidate', direction=direction,
                header=header, **llc)


def csi_data_candidate(record, target, ap):
    """Model DUAL CSI_DATA gate; Protected MPDUs are retained with their CSI."""
    try:
        raw = assemble_api_parts(record)
        header = parse_header(raw)
    except (KeyError, TypeError, ValueError) as exc:
        return dict(accepted=False, reason=f'malformed_layout:{exc}')
    direction = exact_pair_direction(header, target, ap)
    if not direction:
        return dict(accepted=False, reason='not_exact_pair', header=header)
    if not record.get('payload_complete') or record.get('payload_copied') != record.get('payload_len'):
        return dict(accepted=False, reason='incomplete_payload', direction=direction, header=header)
    if record.get('payload_len', 0) <= 0:
        return dict(accepted=False, reason='empty_payload', direction=direction, header=header)
    if record['payload_len'] > CANDIDATE_MAX:
        return dict(accepted=False, reason='payload_over_256', direction=direction, header=header)
    if not record.get('csi_valid'):
        return dict(accepted=False, reason='invalid_csi', direction=direction, header=header)
    return dict(accepted=True, reason='atomic_csi_data', direction=direction,
                protected=bool(header['protected']), header=header, frame_len=len(raw),
                csi_len=record.get('csi_len', 0))


def timeline_buckets(events, width_us=TIMELINE_BUCKET_US):
    """Aggregate timestamped observations into deterministic [start,end) windows."""
    if width_us <= 0:
        raise ValueError('bucket width must be positive')
    buckets = defaultdict(Counter)
    for event in events:
        timestamp = int(event['timestamp_us'])
        if timestamp < 0:
            raise ValueError('negative timestamp')
        bucket_id = timestamp // width_us
        buckets[bucket_id][event['metric']] += int(event.get('count', 1))
    return [dict(bucket_id=i, start_us=i * width_us, end_us=(i + 1) * width_us,
                 counters=dict(sorted(counters.items())))
            for i, counters in sorted(buckets.items())]


def validate_timeline_rows(rows):
    """Validate firmware TIMELINE wire rows; return ordered bucket counters."""
    result = []
    expected_id = None
    previous_end = None
    for row in rows:
        c = row.get('counters', {})
        if c.get('event') != 'TIMELINE':
            continue
        start, end = c.get('start_us'), c.get('end_us')
        bucket_id, span = c.get('bucket_id'), c.get('actual_span_us')
        if c.get('nominal_bucket_us') != TIMELINE_BUCKET_US:
            raise ValueError('unexpected nominal bucket width')
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise ValueError('invalid timeline interval')
        if span != end - start:
            raise ValueError('timeline span mismatch')
        if expected_id is not None and bucket_id != expected_id:
            raise ValueError('timeline bucket id discontinuity')
        if previous_end is not None and start != previous_end:
            raise ValueError('timeline interval gap/overlap')
        result.append(dict(bucket_id=bucket_id, start_us=start, end_us=end,
                           actual_span_us=span,
                           counters={k: v for k, v in c.items()
                                     if k not in ('event', 'mode', 'nominal_bucket_us',
                                                  'bucket_id', 'start_us', 'end_us', 'actual_span_us')}))
        expected_id = bucket_id + 1
        previous_end = end
    return result
