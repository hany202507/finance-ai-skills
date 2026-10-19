# -*- coding: utf-8 -*-
"""판 설정. PUBLIC 이 참이면 출력 폴더에 아래 이름의 파일만 남긴다.

계산(run.py, yangdo_calculate)은 계산근거 엑셀 하나, 신고서(make_return.py, yangdo_forms)는 신고서 PDF 두 벌과 계산근거 엑셀이다.
결과 JSON, 검토·질문·확인 문서, 신고값 JSON 은 쓰지 않고, 상태·합계·확인사항·경고·질문·다루지않음·사람이 할 일은 화면 출력과
MCP 응답으로만 낸다.

코드는 이 값을 쓸 때마다 모듈에서 읽는다(from yangdo import edition 뒤 edition.PUBLIC). 시험이 값을 바꿔 그 동작을 볼 수 있게
하려는 것이다.
"""
PUBLIC = True

WORKBOOK = "양도소득세_계산근거.xlsx"
FORM_NATIONAL, FORM_LOCAL = "양도소득세_신고서.pdf", "지방소득세_신고서.pdf"
PUBLIC_CALC_OUTPUTS = (WORKBOOK,)                               # 계산(run.py, yangdo_calculate)이 남기는 파일
PUBLIC_RETURN_OUTPUTS = (FORM_NATIONAL, FORM_LOCAL, WORKBOOK)   # 신고서 단계(make_return.py, yangdo_forms)가 남기는 파일
