"""감사 모듈 공통 예외."""


class MissingInput(Exception):
    """감사인이 입력해야 하는 값이 비어 있다. 기본값을 지어 넣지 않고 그 계산을 멈춘다."""

    def __init__(self, key: str):
        super().__init__(f"감사인 입력이 없다: {key}")
        self.key = key


class DefinitionError(Exception):
    """정의 파일(YAML)이 규칙에 맞지 않는다."""


class IntakeError(Exception):
    """받은 자료를 읽거나 검증하다 멈춘다."""
