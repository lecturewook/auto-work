"""숫자 모양과 의미(단위)를 나누어 처리. float로 비교하지 않는다."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation, localcontext

KEY_FIELDS = ('부서코드', '사업코드', '기간', '예산구분', '지표코드', '세부차원', '집계수준', '재원')
HEADERS = list(KEY_FIELDS) + ['값', '단위']


def key_complete(key):
    return set(key) == set(KEY_FIELDS) and all(isinstance(key[k], str) and key[k].strip() for k in KEY_FIELDS)


def normalize(raw, unit, rules):
    original = '' if raw is None else str(raw)
    s = unicodedata.normalize('NFKC', original).strip()
    result = dict(original=original, cleaned=s, value=None, base_unit=None, steps=[], state='숫자')
    if not s:
        result['state'] = '빈칸'
        return result
    if s in ('-', '—', '–'):
        result['state'] = '대시 의미 미확인'
        return result
    if s in ('해당 없음', '해당없음', 'N/A'):
        result['state'] = '해당 없음'
        return result
    if any(t in s for t in ('약', '내외', '이상', '이하', '~', '≈')):
        result['state'] = '표시 정밀도 확인 필요'
        return result
    if s.startswith(('△', '▲', '(')):
        result['state'] = '감액 표기 확인 필요'
        return result
    u = unicodedata.normalize('NFKC', str(unit or '')).replace(' ', '')
    units = rules['units']
    # 단위가 원문에 직접 붙은 경우에도 충돌 여부를 확인한다.
    for suffix in sorted(units, key=len, reverse=True):
        compact = s.replace(' ', '')
        if compact.endswith(suffix):
            if u and u != suffix:
                result['state'] = '단위 충돌'
                return result
            u = suffix
            s = compact[:-len(suffix)]
            break
    if not u or u not in units:
        result['state'] = '단위 불명'
        return result
    if not re.fullmatch(r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', s):
        result['state'] = '숫자 해석 불가'
        return result
    digits = s.replace(',', '')
    if len(digits) > 60:
        result['state'] = '숫자 자릿수 제한'
        return result
    result['steps'].append('문자 정리: 쉼표 제거, 유니코드 폭 통일')
    try:
        with localcontext() as ctx:
            ctx.prec = 100
            value = Decimal(digits) * Decimal(units[u][1])
        result.update(value=format(value, 'f'), base_unit=units[u][0], unit=u)
        result['steps'].append(f'{digits} × {units[u][1]} = {result["value"]} {units[u][0]}')
    except InvalidOperation:
        result['state'] = '숫자 해석 불가'
    return result
