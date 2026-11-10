# 소현리치랩 링크페이지

인스타그램 @sohyun_richlab 프로필용 링크페이지 → https://revi404.github.io/sohyunrichlab/
소현생정 링크페이지(https://revi404.github.io/sohyunguide/)와 같은 구성에 소현리치랩 디자인 시스템(블루·골드)을 적용했습니다.

## 자동으로 되는 것

| 항목 | 방식 | 주기 |
|---|---|---|
| 이번 주 청약단지 탭 | `sohyun-blog-kit/richlab/calendar.json`(티스토리 홈 '다가오는 7일 청약 일정'과 같은 데이터)을 화면이 바로 읽어 오늘부터 7일 안의 청약 접수·당첨 발표를 표시. 주소가 막히면 `data/calendar.json` 사본 사용 | 열 때마다(사본은 30분마다) |
| 분석 리포트 탭 | 티스토리 상위 카테고리(지역 하위 카테고리 합침)별 최신 글. 카테고리는 블로그 홈 메뉴에서 읽어 새 카테고리도 자동 추가, 글이 없는 카테고리는 숨김 | 30분마다 |
| 공공임대·분양 공고 파일 | `scripts/collect_public_housing.py`가 LH·GH·SH와 지방 개발공사 공고를 `data/public_housing.json` 한 파일로 정리 (아래 설명) | 하루 4번(07·12·17·21시) |
| 배포 | GitHub Actions → GitHub Pages | 수집 직후 · 파일 수정 시 |

- 공고 요약 글이 있는 단지는 '요약 글' 표시와 함께 티스토리 글로, 없으면 블로그 홈으로 연결됩니다.
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

## 공공임대·분양 공고 파일: `data/public_housing.json`

공개 주소: https://revi404.github.io/sohyunrichlab/data/public_housing.json (수집 후 다음 배포 때 반영, 최대 30분)

| 출처 | 방식 | 담기는 내용 |
|---|---|---|
| LH | 공공데이터포털 LH 분양임대공고 API | 임대·주거복지·분양·신혼희망타운 공고, 상태, 마감일, 원문 링크 |
| 마이홈 | 공공데이터포털 마이홈 공공주택 모집공고 API | 단지 주소·공급 호수·보증금·월임대료·계약금 등 (`houses`). LH 공고에 붙이고 지방 개발공사 공고는 따로 추가 |
| GH | 주택청약·임대센터 청약공고 목록 | 임대주택·매입임대 공고, 지역, 마감일, 상태 |
| SH | 공고 및 공지 게시판(주택임대·주택분양) 목록 | 게시글 제목·날짜·링크. `kind`가 `모집공고`인 것만 새 공고, 나머지는 당첨자 발표·안내 |

- 처음 한 번: 저장소 Settings → Secrets and variables → Actions → New repository secret 에 이름 `DATA_GO_KR_KEY`, 값은 공공데이터포털 일반 인증키(Decoding)
- 바로 돌리기: Actions → "공공임대·분양 공고 수집" → Run workflow
- 상세(`detail`)는 진행 중인 LH 공고, GH 공고 전체, SH 모집공고 글에만 붙습니다. 공고당 한 번만 읽고 이후에는 저장된 값을 다시 씁니다. 파일 원본은 저장하지 않고 이름과 주소만 남깁니다.
- 공고일 기준 최근 90일과 아직 접수 중인 공고를 담습니다. 한 출처가 실패하면 그 출처는 직전 수집분을 그대로 두고 `sources`에 실패로 표시합니다.
- SH·GH 사이트가 GitHub 서버 접속을 막으면 PC에서 `python scripts/collect_public_housing.py --only sh,gh` 실행 후 push 하면 됩니다.

| 항목 | 뜻 |
|---|---|
| `org` · `deal` · `type` | 기관 · 임대/분양 · 유형(국민임대, 행복주택 등) |
| `notice_date` · `apply_start` · `apply_end` · `winner_date` | 공고일 · 접수 시작 · 접수 마감 · 당첨 발표 |
| `status` | 공고중 · 접수중 · 접수마감 등 (SH는 없음) |
| `houses[]` | 단지별 `name` `addr` `units`(공급 호수) `deposit`(보증금) `rent`(월임대료) `down`·`middle`·`balance`(계약금·중도금·잔금), 원 단위 |
| `url` | 원문 공고 주소 (GH는 목록 화면) |
| `detail.files[]` | 첨부파일 `name` `kind` `url` (SH는 내려받기 주소 대신 `preview_url` 미리보기) |
| `detail.images[]` | LH 단지 이미지(위치도·단지배치도·조감도·평면도 등) `site` `kind` `url` |
| `detail.schedule[]` | 접수·서류 제출·당첨 발표·계약 일정 |
| `detail.sites[]` · `detail.types[]` | 단지 주소·세대수·전용면적·입주 예정월 · GH 주택형별 면적·호수 |
