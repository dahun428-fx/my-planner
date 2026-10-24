"""작업 스케줄러 XML 템플릿 (스펙 5.1, S4, S6).

등록 스크립트(`scripts/register_task.ps1`)처럼 자리표시자를 채우고 UTF-16으로 바꾼 뒤 ElementTree로 읽는다.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

# 일부러 &를 넣었다: 스크립트가 값을 XML로 이스케이프해 넣는지 본다
ROOT = r"E:\my-planner & co"
PYTHONW = ROOT + r"\.venv\Scripts\pythonw.exe"
USER = r"LAPTOP\jungdahun"


def render(name: str, **values: str) -> ET.Element:
    text = (SCRIPTS / name).read_text(encoding="utf-8")
    assert text.isascii()  # UTF-16 LE로 바꿔도 잃는 글자가 없다
    defaults = {"PYTHONW": escape(PYTHONW), "ROOT": escape(ROOT), "USER": escape(USER)}
    for key, value in {**defaults, **values}.items():
        text = text.replace("{{" + key + "}}", value)
    assert "{{" not in text, "채우지 않은 자리표시자가 남았다"
    return ET.fromstring(text.encode("utf-16"))  # 등록 스크립트처럼 UTF-16(BOM)으로 저장한 모양


def main_task() -> ET.Element:
    return render("task_my-planner.xml.tmpl")


def find(el: ET.Element, path: str) -> ET.Element:
    found = el.find(path, NS)
    assert found is not None, path
    return found


def text(el: ET.Element, path: str) -> str:
    return (find(el, path).text or "").strip()


def test_main_task_settings():
    task = main_task()
    assert task.tag == f"{{{NS['t']}}}Task"
    assert float(task.get("version")) >= 1.2
    s = find(task, "t:Settings")
    assert text(s, "t:DisallowStartIfOnBatteries") == "false"
    assert text(s, "t:StopIfGoingOnBatteries") == "false"
    assert text(s, "t:ExecutionTimeLimit") == "PT0S"
    assert text(s, "t:MultipleInstancesPolicy") == "IgnoreNew"
    assert text(s, "t:RestartOnFailure/t:Interval") == "PT1M"
    assert text(s, "t:RestartOnFailure/t:Count") == "999"
    assert text(s, "t:RunOnlyIfIdle") == "false"
    assert text(s, "t:Enabled") == "true"
    p = find(task, "t:Principals/t:Principal")
    assert text(p, "t:LogonType") == "InteractiveToken"
    assert text(p, "t:UserId") == USER
    assert text(p, "t:RunLevel") == "LeastPrivilege"


def test_main_task_triggers():
    triggers = find(main_task(), "t:Triggers")
    tags = [t.tag.split("}")[1] for t in triggers]
    assert sorted(tags) == ["EventTrigger", "LogonTrigger", "TimeTrigger"]

    logon = find(triggers, "t:LogonTrigger")
    assert text(logon, "t:UserId") == USER
    assert text(logon, "t:Enabled") == "true"

    # 절전 복귀: System 로그, Power-Troubleshooter, 이벤트 ID 1
    event = find(triggers, "t:EventTrigger")
    query = ET.fromstring(text(event, "t:Subscription"))
    select = query.find("Query/Select")
    assert select is not None and select.get("Path") == "System"
    assert "Provider[@Name='Microsoft-Windows-Power-Troubleshooter']" in select.text
    assert "EventID=1]" in select.text

    # 5분 워치독: 끝나지 않는 반복(Duration 없음). IgnoreNew라 실행 중이면 아무 일도 없다(S6)
    watchdog = find(triggers, "t:TimeTrigger")
    assert text(watchdog, "t:Repetition/t:Interval") == "PT5M"
    assert watchdog.find("t:Repetition/t:Duration", NS) is None
    assert text(watchdog, "t:Repetition/t:StopAtDurationEnd") == "false"
    assert text(watchdog, "t:StartBoundary")
    assert text(watchdog, "t:Enabled") == "true"


def test_main_task_working_directory_is_root():
    actions = find(main_task(), "t:Actions")
    assert actions.get("Context") == "Author"
    execs = actions.findall("t:Exec", NS)
    assert len(execs) == 1
    assert text(execs[0], "t:Command") == PYTHONW
    assert text(execs[0], "t:Arguments") == "-m my_planner"
    assert text(execs[0], "t:WorkingDirectory") == ROOT


WEEKDAYS = "<Monday /><Tuesday /><Wednesday /><Thursday /><Friday />"
WEEKEND = "<Saturday /><Sunday />"


def wake_trigger(hhmm: str, days: str) -> str:
    """등록 스크립트가 `wake_times` 출력 한 줄마다 하는 것처럼 트리거 조각을 채운다."""
    return (SCRIPTS / "task_my-planner-wake_trigger.xml.tmpl").read_text(encoding="utf-8").replace(
        "{{TIME}}", hhmm
    ).replace("{{DAYS}}", days)


def test_wake_task_has_wake_to_run_battery_and_noop_action():
    triggers_xml = wake_trigger("08:55", WEEKDAYS) + wake_trigger("09:55", WEEKEND)
    task = render("task_my-planner-wake.xml.tmpl", WAKE_TRIGGERS=triggers_xml)
    assert float(task.get("version")) >= 1.2

    s = find(task, "t:Settings")
    assert text(s, "t:WakeToRun") == "true"
    assert text(s, "t:DisallowStartIfOnBatteries") == "false"
    assert text(s, "t:StopIfGoingOnBatteries") == "false"
    assert text(s, "t:MultipleInstancesPolicy") == "IgnoreNew"
    assert text(find(task, "t:Principals/t:Principal"), "t:LogonType") == "InteractiveToken"

    # 하는 일은 없다: 창 없는 pythonw로 `-c pass`만
    execs = find(task, "t:Actions").findall("t:Exec", NS)
    assert len(execs) == 1
    assert text(execs[0], "t:Command") == PYTHONW
    assert text(execs[0], "t:Arguments") == "-c pass"

    # wake_times 한 줄 = 캘린더 트리거 하나(매주, 평일 또는 주말)
    cal = find(task, "t:Triggers").findall("t:CalendarTrigger", NS)
    assert [text(c, "t:StartBoundary")[-8:] for c in cal] == ["08:55:00", "09:55:00"]
    days = [[d.tag.split("}")[1] for d in find(c, "t:ScheduleByWeek/t:DaysOfWeek")] for c in cal]
    assert days == [["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], ["Saturday", "Sunday"]]
    assert all(text(c, "t:ScheduleByWeek/t:WeeksInterval") == "1" for c in cal)


def test_scripts_do_not_use_psscriptroot_in_param_defaults():
    # Windows PowerShell 5.1 + -File 에서는 param 기본값 계산 때 $PSScriptRoot가 비어 있다
    import re
    from pathlib import Path

    for name in ("register_task.ps1", "check_tasks.ps1"):
        text = (Path(__file__).parent.parent / "scripts" / name).read_text(encoding="utf-8-sig")
        param_block = re.search(r"param\((.*?)\n\)", text, re.DOTALL).group(1)
        assert "$PSScriptRoot" not in param_block, name
