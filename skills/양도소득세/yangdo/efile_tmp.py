# -*- coding: utf-8 -*-
"""전자신고 파일을 검증하는 동안 쓰는 임시 폴더. 만들기, 이 도구의 폴더인지 가리기, 지우기가 이 모듈 한 곳에 있다.

생성기(efile.write)가 출력 폴더 아래에 「.efile-」 + 여덟 글자 이름으로 만들고, 그 안에 검증 전 전자신고 파일(제출용 이름)과
신고값 사본(인적사항이 들어 있다)을 둔다. 실행이 강제로 끝나면 폴더가 남을 수 있어 다음 실행이 쓸어 낸다.
생성기, 출력 함수(outputs.clear_all), 실행 진입점(make_return)이 같은 함수를 쓴다.

쓸어 낼 때는 이 도구가 만든 폴더만 지운다. 이름이 「.efile-」 로 시작해도 이름 꼴이 다르거나(예: 「.efile-메모」) 안에
이 도구가 쓰지 않는 파일이나 폴더가 있으면 지우지 않는다.

지우지 않은 폴더 가운데 이름 꼴이 맞고 안에 이 도구의 파일(신고값 사본, 제출용 이름의 전자신고 파일, 검증안됨.tmp)이 하나라도
있는 것은 따로 알린다(mixed, MIXED_NOTE). 강제로 끝난 실행의 폴더에 다른 프로그램이 파일을 하나 끼워 넣은 경우다
(예: .DS_Store). 인적사항이 든 신고값 사본과 검증하지 않은 전자신고 파일이 알림 없이 남지 않게 하려는 것이다.
이 도구의 파일이 하나도 없는 폴더는 사용자의 것으로 보고 알리지 않는다.
"""
import os
import re
import shutil
import tempfile

PREFIX = ".efile-"                        # 임시 폴더 이름의 머리
SUFFIX = re.compile(r"^[a-z0-9_]{8}$")    # tempfile.mkdtemp 가 붙이는 여덟 글자(영문 소문자, 숫자, 밑줄)
RV_COPY = "신고값.json"                   # 검증기에 넘기는 신고값 사본
REJECTED_NAME = "검증안됨.tmp"            # 지우지 못한 임시 파일에 붙이는 이름(제출용 이름이 아니다)
SUBMIT_NAME = re.compile(r"^[0-9]{8}[A-Z][0-9]{6}\.[0-9]{2}$")       # 제출용 파일 이름 꼴(규격서 p20)
# 앞선 실행의 임시 폴더를 지우지 못했을 때 알리는 문장(폴더 이름만 싣는다)
LEFT_NOTE = "앞선 실행이 남긴 임시 폴더 %s 를 지우지 못했다. 인적사항이 든 임시 파일이 남아 있을 수 있으니 직접 지운다"
# 이름 꼴이 맞고 이 도구의 파일이 있지만 다른 파일이나 폴더가 함께 있어 지우지 않은 폴더를 알리는 문장(폴더 이름만 싣는다)
MIXED_NOTE = ("임시 폴더 꼴의 폴더 %s 에 다른 파일이 함께 있어 지우지 않았다. 인적사항이 든 신고값 사본이나 검증하지 않은 "
              "전자신고 파일이 있을 수 있으니 직접 확인해 지운다")


def make(out_dir):
    """출력 폴더 아래에 임시 폴더를 만들고 경로를 돌려준다."""
    return tempfile.mkdtemp(prefix=PREFIX, dir=out_dir)


def _own_file(name):
    return name in (RV_COPY, REJECTED_NAME) or bool(SUBMIT_NAME.match(name))


def _shaped(out_dir, name):
    """이름이 「.efile-」 + 여덟 글자 꼴이고 링크가 아닌 폴더인지."""
    if not (name.startswith(PREFIX) and SUFFIX.match(name[len(PREFIX):])):
        return False
    path = os.path.join(out_dir, name)
    return os.path.isdir(path) and not os.path.islink(path)


def is_own(out_dir, name):
    """출력 폴더 안의 name 이 이 도구가 만든 임시 폴더인지.

    이름이 「.efile-」 + 여덟 글자 꼴이고, 링크가 아닌 폴더이고, 안에 이 도구의 파일(제출용 이름의 전자신고 파일, 신고값 사본,
    검증안됨.tmp)만 있어야 한다. 빈 폴더도 이 도구의 것이다(파일을 쓰기 전에 끝난 실행). 안을 읽을 수 없으면 이름 꼴만으로
    이 도구의 것으로 본다. 그런 폴더는 지워지지 않아 남았다고 알리게 된다.
    """
    if not _shaped(out_dir, name):
        return False
    try:
        with os.scandir(os.path.join(out_dir, name)) as entries:
            return all(_own_file(e.name) and e.is_file(follow_symlinks=False) for e in entries)
    except OSError:
        return True


def is_mixed(out_dir, name):
    """이름 꼴은 이 도구의 임시 폴더인데 이 도구의 파일과 다른 파일·폴더가 함께 있어 지우지 않는 폴더인지.

    안에 신고값 사본, 제출용 이름의 파일, 검증안됨.tmp 가운데 하나라도 있어야 한다. 하나도 없으면 사용자의 폴더로 본다.
    """
    if not _shaped(out_dir, name) or is_own(out_dir, name):
        return False
    try:
        with os.scandir(os.path.join(out_dir, name)) as entries:
            return any(_own_file(e.name) for e in entries)
    except OSError:
        return False


def remove(work):
    """임시 폴더를 지운다. 다 지웠으면 None, 남았으면 알릴 문장(폴더·파일 이름만).

    폴더 삭제는 막힐 수 있다(Windows 에서 백신·색인기가 파일을 잡은 경우). 그래서 제출용 이름의 파일을 먼저 지우고,
    지우지 못하면 제출용이 아닌 이름으로 바꾼다. 검증을 통과하지 않은 파일이 제출용 이름으로 남지 않게 하려는 것이다.
    """
    try:
        names = os.listdir(work)
    except OSError:
        names = []
    for n in names:
        if not SUBMIT_NAME.match(n):
            continue
        path = os.path.join(work, n)
        try:
            os.remove(path)
        except OSError:
            try:
                os.replace(path, os.path.join(work, REJECTED_NAME))
            except OSError:
                pass
    try:
        shutil.rmtree(work)
    except OSError:
        pass
    if not os.path.lexists(work):
        return None
    base = os.path.basename(work)
    try:
        stuck = sorted(n for n in os.listdir(work) if SUBMIT_NAME.match(n))
    except OSError:
        stuck = []
    if stuck:
        return ("임시 폴더 %s 에 검증을 통과하지 않은 파일 %s 이 제출용 이름으로 남아 있다. 제출하지 말고 폴더째 직접 지운다"
                % (base, ", ".join(stuck)))
    return "임시 폴더 %s 를 지우지 못했다. 신고값 임시 JSON 과 검증 전 임시 파일(인적사항)이 남아 있을 수 있으니 직접 지운다" % base


def left(out_dir):
    """출력 폴더에 남아 있는 이 도구의 임시 폴더 이름 목록(이름순). 폴더를 읽을 수 없으면 빈 목록."""
    try:
        return [n for n in sorted(os.listdir(out_dir)) if is_own(out_dir, n)]
    except OSError:
        return []


def sweep(out_dir):
    """앞선 실행이 남긴 이 도구의 임시 폴더를 지운다. 지우지 못한 폴더마다 (폴더 이름, 알릴 문장)."""
    stuck = []
    for n in left(out_dir):
        msg = remove(os.path.join(out_dir, n))
        if msg:
            stuck.append((n, msg))
    return stuck


def mixed(out_dir):
    """다른 파일이 함께 있어 지우지 않는 임시 폴더 꼴의 폴더 이름 목록(이름순, is_mixed). 폴더를 읽을 수 없으면 빈 목록."""
    try:
        return [n for n in sorted(os.listdir(out_dir)) if is_mixed(out_dir, n)]
    except OSError:
        return []


def mixed_notes(out_dir):
    """다른 파일이 함께 있어 지우지 않은 폴더마다 알릴 문장(MIXED_NOTE). 없으면 빈 목록."""
    return [MIXED_NOTE % n for n in mixed(out_dir)]


def left_notes(out_dir):
    """출력 폴더에 남아 있는 임시 폴더마다 알릴 문장. 없으면 빈 목록.

    지우지 못해 남은 이 도구의 폴더(LEFT_NOTE)와, 다른 파일이 함께 있어 지우지 않은 폴더(MIXED_NOTE)를 모두 싣는다.
    """
    return [LEFT_NOTE % n for n in left(out_dir)] + mixed_notes(out_dir)
