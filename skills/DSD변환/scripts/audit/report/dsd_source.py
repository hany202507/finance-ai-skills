"""dsd 원문 글의 요소 위치(2026-10-26, DSD 네 기능 설계 2.5).

contents.xml 을 expat 으로 읽어 요소마다 원문 글에서의 바이트 구간을 남긴다. 원고 엑셀로 고친 칸만 그 구간의 글자를 바꾸고
나머지 바이트는 그대로 둔다(왕복 기준 2 「바이트 같음」). ElementTree 로 문서 전체를 다시 쓰면 SPAN 이 섞인 P 에 줄바꿈이 들어가고
속성 순서 · 빈 요소 꼴이 바뀐다.

    src = Source(raw)                 raw 는 contents.xml 바이트
    src.nodes[k]                      문서 차례 k 번째 요소(위치 번호). tag · attrs · kids · s · se · es · e
    src.text(node)                    요소 안 글 전체(개체 풀린 글. &cr; 은 그대로)
    src.apply([(시작, 끝, 새 바이트)])  구간을 바꾼 새 원문
"""
from __future__ import annotations

import re
import xml.parsers.expat
from dataclasses import dataclass, field

CR = "&cr;"


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict
    k: int                                  # 문서 차례(위치 번호)
    parent: "Node | None" = None
    kids: list = field(default_factory=list)
    text: str = ""                          # 첫 자식 앞 글
    tail: str = ""                          # 닫는 태그 뒤 글
    s: int = 0                              # 여는 태그 「<」
    se: int = 0                             # 여는 태그 「>」 다음
    es: int | None = None                   # 닫는 태그 「</」(빈 요소면 None)
    e: int = 0                              # 닫는 태그 「>」 다음

    def find(self, tag: str) -> "Node | None":
        return next((c for c in self.kids if c.tag == tag), None)

    def findall(self, tag: str) -> list:
        return [c for c in self.kids if c.tag == tag]

    def iter(self):
        yield self
        for c in self.kids:
            yield from c.iter()

    def get(self, name: str, default=None):
        return self.attrs.get(name, default)


def _tag_end(raw: bytes, i: int) -> int:
    """i(「<」)에서 시작한 태그의 「>」 다음 위치. 따옴표 안의 「>」 는 건너뛴다."""
    q = None
    n = len(raw)
    while i < n:
        ch = raw[i]
        if q is not None:
            if ch == q:
                q = None
        elif ch in (0x22, 0x27):
            q = ch
        elif ch == 0x3E:
            return i + 1
        i += 1
    raise ValueError("닫히지 않은 태그")


class Source:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.nodes: list[Node] = []
        self.root: Node | None = None
        stack: list[Node] = []
        p = xml.parsers.expat.ParserCreate("utf-8")
        p.buffer_text = True
        p.ordered_attributes = False

        def start(tag, attrs):
            i = p.CurrentByteIndex
            n = Node(tag, dict(attrs), len(self.nodes), stack[-1] if stack else None, s=i)
            n.se = _tag_end(raw, i)
            if stack:
                stack[-1].kids.append(n)
            else:
                self.root = n
            self.nodes.append(n)
            stack.append(n)

        def end(tag):
            n = stack.pop()
            i = p.CurrentByteIndex
            if i == n.s or raw[n.se - 2:n.se] == b"/>":          # 빈 요소 <X/>
                n.es, n.e = None, n.se
            else:
                n.es, n.e = i, _tag_end(raw, i)

        def data(t):
            if not stack:
                return
            cur = stack[-1]
            if cur.kids:
                cur.kids[-1].tail += t
            else:
                cur.text += t

        p.StartElementHandler = start
        p.EndElementHandler = end
        p.CharacterDataHandler = data
        p.Parse(raw, True)

    def text(self, n: Node) -> str:
        out = [n.text]
        for c in n.kids:
            out.append(self.text(c))
            out.append(c.tail)
        return "".join(out)

    def inner(self, n: Node) -> bytes:
        return b"" if n.es is None else self.raw[n.se:n.es]

    def outer(self, n: Node) -> bytes:
        return self.raw[n.s:n.e]

    def apply(self, edits: list[tuple[int, int, bytes]]) -> bytes:
        """구간 바꾸기. 겹치는 구간이 있으면 멈춘다."""
        out, pos = [], 0
        for a, b, new in sorted(edits, key=lambda x: (x[0], x[1])):
            if a < pos:
                raise ValueError(f"겹치는 고침 구간: {a} < {pos}")
            out.append(self.raw[pos:a])
            out.append(new)
            pos = b
        out.append(self.raw[pos:])
        return b"".join(out)


def escape(text: str) -> str:
    """원고 글 → 요소 글. 줄바꿈은 &cr;(원문에는 &amp;cr;), 꺾쇠 · & 는 개체로."""
    t = str(text).replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return t.replace("\n", "&amp;cr;")


def shown(text: str) -> str:
    """요소 글 → 원고 글. &cr; 는 칸 안 줄바꿈, 앞뒤 줄바꿈 표시와 연속 공백은 그대로 둔다(원문 그대로)."""
    return str(text).replace(CR, "\n")


_WS = re.compile(r"[ \t\r\n]+")


def flat(text: str) -> str:
    """판독용 글(검증용 판독과 같게): &cr; 와 연속 공백을 띄어쓰기 하나로."""
    return _WS.sub(" ", str(text).replace(CR, " ")).strip()
