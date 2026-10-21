# 소현리치랩 링크페이지

인스타그램 @sohyun_richlab 프로필용 링크페이지 → https://revi404.github.io/sohyunrichlab/
소현생정 링크페이지(https://revi404.github.io/sohyunguide/)와 같은 구성에 소현리치랩 디자인 시스템(블루·골드)을 적용했습니다.

## 자동으로 되는 것

| 항목 | 방식 | 주기 |
|---|---|---|
| 이번 주 청약단지 탭 | `sohyun-blog-kit/richlab/calendar.json`(티스토리 홈 '다가오는 7일 청약 일정'과 같은 데이터)을 화면이 바로 읽어 오늘부터 7일 안의 청약 접수·당첨 발표를 표시. 주소가 막히면 `data/calendar.json` 사본 사용 | 열 때마다(사본은 30분마다) |
| 분석 리포트 탭 | 티스토리 상위 카테고리(지역 하위 카테고리 합침)별 최신 글. 카테고리는 블로그 홈 메뉴에서 읽어 새 카테고리도 자동 추가, 글이 없는 카테고리는 숨김 | 30분마다 |
| 배포 | GitHub Actions → GitHub Pages | 수집 직후 · 파일 수정 시 |

- 공고 요약 글이 있는 단지는 '요약 글' 표시와 함께 티스토리 글로, 없으면 청약홈 공고로 연결됩니다.
- 바로 반영하려면: 저장소 → Actions → "분석 리포트 수집 및 배포" → Run workflow
- 처음 한 번: 저장소 Settings → Pages → Source 를 **GitHub Actions** 로 지정

## 직접 수정하는 곳: `config.json`

| 하고 싶은 것 | 수정 위치 |
|---|---|
| 상단 공지 띄우기 | `notice.show`를 `true`, `text`·`url` 입력 |
| 바로가기 버튼 | `links` (`icon`: blog·mail·insta·youtube·link, `color`: navy) |
| 다른 채널 묶음(가로 버튼 2개) | `links`의 `"type": "pair"` 항목. 지금은 소현생정 블로그·인스타 (`color`: `green`) |
| 카테고리 순서·이름·숨김 | `blog.order` · `blog.labels` · `blog.hidden` |
| 카테고리별 글 개수 / 전체 탭 글 개수 | `blog.perCategory` / `blog.allCount` |
| 청약 일정 표시 기간·최대 건수 | `week.days` · `week.max` |
| 클릭 통계 | GoatCounter 코드를 `goatcounter`에 입력 |

미리보기에서 날짜를 바꿔 보려면 주소 뒤에 `?today=2026-10-22` 를 붙입니다.
