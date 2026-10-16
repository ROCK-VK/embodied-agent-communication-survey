"""Decode compact-v1 UART records without changing CSI bytes or PHY metadata."""
import json


def decode_record(line):
    r = json.loads(line)
    if not isinstance(r, dict):
        raise ValueError('record must be an object')
    if 'e' not in r:
        return r
    if r['e'] not in ('F', 'C'):
        raise ValueError('unknown compact record')
    mapping = dict(i='wire_record_id', t='timestamp', fc='fc', q='seq_ctrl',
                   ta='ta', ra='ra', f='format', ch='channel', s='second',
                   r='rssi', st='rx_state', rate='rate', pr='app_probe_status')
    out = {v: r[k] for k, v in mapping.items()}
    for key in ('wire_record_id', 'timestamp', 'fc', 'seq_ctrl', 'format'):
        if type(out[key]) is not int:
            raise ValueError('invalid integer metadata')
    fc = out['fc']
    out.update(event='FRAME' if r['e'] == 'F' else 'CSI', wire_format='compact-v1',
               target=1, ta_present=1, frame_type=(fc >> 2) & 3,
               subtype=(fc >> 4) & 15, to_ds=(fc >> 8) & 1,
               from_ds=(fc >> 9) & 1, protected=(fc >> 14) & 1)
    if r['e'] == 'C':
        fields = dict(src='source', v='estimate_valid', w='first_word_invalid',
                      n='len', c='copied', g1='he_siga1', g2='he_siga2',
                      x='rx_seq', hx='data_hex')
        out.update({v: r[k] for k, v in fields.items()})
        if len(r['hx']) != 2*r['c'] or len(bytes.fromhex(r['hx'])) != r['c']:
            raise ValueError('CSI hex length mismatch')
    if r['pr'] == 4:
        out.update(app_run_id=r['rid'], app_packet_id=r['pid'], app_sender_mono_ns=r['tx'])
    return out
