"""서식 플러그인 이름표(tools/sync_engine.py 가 만듦)."""
_FORMS = [{'code': '34'}, {'code': '8갑'}, {'code': '8을'}, {'code': '8부표2'}, {'code': '8부표3'}, {'code': '조특2'}, {'code': '조특10의9'}, {'code': '조특3_1'}, {'code': '48'}, {'code': '16의2'}, {'code': '40갑'}, {'code': '40을'}, {'code': '19갑'}, {'code': '19을'}, {'code': '9'}, {'code': '선급비용명세서'}, {'code': 'std_bs_fin'}, {'code': 'std_bs_fin_sum'}, {'code': 'std_is_fin'}]


def engine_forms():
    return [dict(x) for x in _FORMS]
