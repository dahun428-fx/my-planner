# 두뇌는 하네스 도구(`mcp__planner__*`)만 쓸 수 있고, 파일·셸·웹 도구는 하나도 없다

데이터를 바꾸는 길을 도구 하나로 좁혀야 확인 문구, 원문 기록, 재실행 판정이 성립한다. Agent SDK의 `allowed_tools`는 자동 승인만 할 뿐 도구를 막지 않는다. 그래서 `tools=[]`, `permission_mode="dontAsk"`, 엄격한 MCP 설정, `setting_sources=[]`, claude.ai 커넥터와 auto memory를 끄는 환경 변수를 함께 쓴다. 이 설정이 실제로 막히는지는 스파이크 S2, S3에서 확인한다.
