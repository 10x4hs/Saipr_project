# Grill: 해독(偕讀) 반응형 UI
Date: 2026-10-31

## Intent
'함께읽기'를 **해독(偕讀)** — 偕(함께 해) + 讀(읽을 독) — 으로 이름을 바꾸고, 휴대폰 폭에 갇힌 앱을 넓은 화면에서도 제대로 쓰이게 만든다. 동시에 손에 반응하는 상호작용을 더해 선생님(개발자)·클라이언트에게 완성도를 보여 준다.

## Constraints
- 시연은 PC 브라우저와 휴대폰이 비슷한 비중 — 어느 한쪽이 "늘린 것"처럼 보이면 안 된다.
- 지난번 폰 렉 피드백 → 새 효과는 transform/opacity만, 폰에서 프레임 예산을 넘지 않게.
- 읽은 시간 검증·스포일러 가드 규칙은 그대로.
- 머지·배포는 사용자가 확인한 뒤에.

## Key decisions
- Decision: '반응형' = 화면 크기 대응 + 손에 반응하는 UI 둘 다. Reason: 사용자 선택.
- Decision: PC는 왼쪽 세로 사이드바 + 넓은 본문(홈 3D 나선은 화면 가득, 탐색은 다열 격자). Alternative considered: 가운데 폰 앱 + 양옆 패널, 화면별 전용 배치.
- Decision: PC 리더는 펼친 두 쪽(StPageFlip landscape) + 오른쪽 친구 진행·반응 열. Reason: '함께 읽는다'가 한 화면에 드러남. 한 청크 안의 장을 나누는 구조라 체류시간 규칙은 그대로. Alternative considered: 반응은 필요할 때만, 문단 옆 여백 말풍선.
- Decision: 손맛 3가지 — 책이 포인터(PC)·기기 기울기(폰) 따라 기울기, 화면 전환 이어짐(View Transitions), 실시간 반응·추월 알림이 아바타로 날아오기. 제외: 눌림 스프링+진동.
- Decision: 로고는 한자 **偕讀** 크게 + **해독** 작게. Reason: 한글만 쓰면 解毒/解讀으로 읽힘.
- Decision: 이름 변경은 화면·문서 + 배포 주소(haedok.vercel.app, 비어 있음 확인). 예전 주소 saipr-reading.vercel.app은 링크 보존을 위해 유지.
- Decision: PR까지 만들고 PC·폰 스크린샷으로 확인받은 뒤 머지·배포.

## Surfaced assumptions
- iOS 기기 기울기는 사용자 제스처 후 권한 요청이 필요 — 거절하면 조용히 끈다.
- 태블릿(768px~)은 아이콘만 있는 좁은 사이드바, 1100px~ 에서 이름까지 보이는 사이드바와 리더 반응 열.

## Out of scope
- 저장소 이름 변경(Saipr_project), 눌림 진동 효과.
