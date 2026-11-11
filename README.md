# 소현리치랩 링크페이지

인스타그램 @sohyun_richlab 프로필용 링크페이지 → https://revi404.github.io/sohyunrichlab/
소현생정 링크페이지(https://revi404.github.io/sohyunguide/)와 같은 구성에 소현리치랩 디자인 시스템(블루·골드)을 적용했습니다.

## 자동으로 되는 것

| 항목 | 방식 | 주기 |
|---|---|---|
| 이번 주 청약단지 탭 | `sohyun-blog-kit/richlab/calendar.json`(티스토리 홈 '다가오는 7일 청약 일정'과 같은 데이터)을 화면이 바로 읽어 오늘부터 7일 안의 청약 접수·당첨 발표를 표시. 주소가 막히면 `data/calendar.json` 사본 사용 | 열 때마다(사본은 30분마다) |
| 분석 리포트 탭 | 티스토리 상위 카테고리(지역 하위 카테고리 합침)별 최신 글. 카테고리는 블로그 홈 메뉴에서 읽어 새 카테고리도 자동 추가, 글이 없는 카테고리는 숨김 | 30분마다 |
| 공공임대·분양 공고 파일 | `scripts/collect_public_housing.py`가 LH·GH·SH와 지방 개발공사 공고를 `data/public_housing.json` 한 파일로 정리 (아래 설명) | 06~22시 매시간 시도(GitHub 사정으로 일부 누락될 수 있음) |
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

## 공고 요약 파일: `data/public_housing_digest.json`

공개 주소: https://revi404.github.io/sohyunrichlab/data/public_housing_digest.json · 스레드 작성처럼 큰 공고 파일 전체가 필요 없는 곳에서 이 요약만 읽습니다(약 20KB, 목표 40KB 이하).

| 항목 | 뜻 |
|---|---|
| `updated` · `today` · `source_updated` | 만든 시각(KST) · 기준 날짜 · 원본 `public_housing.json` 의 수집 시각 |
| `counts` | `active`(진행 중 모집공고) `new_3d` `closing_3d` `opening_7d` 해당 건수(최대 건수로 자르기 전) |
| `new` | 공고일이 오늘 포함 최근 3일인 공고, 점수 높은 순 최대 15건 |
| `closing` | 접수 마감이 오늘~3일 뒤인 공고, 마감 빠른 순 최대 10건 |
| `opening` | 접수 시작이 내일~7일 뒤인 공고, 시작 빠른 순 최대 10건 |

- 항목: `id` `org` `deal` `type` `title` `region` `city` `notice_date` `apply_start` `apply_end` `winner_date` `units` `houses`(최대 3곳) `house_count` `areas`(GH 주택형 면적·호수, 최대 5) `move_in` `url` `has_text`(`data/notice_text/<id>.json` 있음) `score` `reasons`. 값이 없는 칸은 넣지 않습니다.
- 대상은 모집공고만입니다. LH·마이홈·GH 는 공고중·접수중·정정공고중인 것, SH 는 상태·접수일이 없어 공고일이 최근 3일인 것만 `new` 에 들어갑니다. 가정어린이집·상가는 뺍니다.
- 점수(수도권, 공급 호수, 분양, SH/GH, 관심 유형, 정정·추가·선착순 가감)는 `scripts/build_public_digest.py` 맨 위 상수 표에서 고칩니다. 점수를 매긴 사유는 `reasons` 에 한글로 남습니다.
- 공고 수집 직후 같은 워크플로에서 만듭니다. 직접 실행: `python scripts/build_public_digest.py` (날짜를 바꿔 시험: `--today 2026-11-14`). 날짜 외에 바뀐 내용이 없으면 파일을 다시 쓰지 않습니다.

## 공고문 추출 파일: `data/notice_text/<공고 id>.json`

공고문 PDF를 받아 쪽별 글(`pages[].text`)과 표(`pages[].tables`)만 남깁니다. PDF 원본은 저장하지 않습니다.

- 자동: 수집 때마다 아직 뽑지 않은 진행 중 모집공고 중 GH 전체와 LH 분양(신혼희망타운 포함)을 최근 것부터 3건씩
- 지정: Actions → "공공임대·분양 공고 수집" → Run workflow 의 `ids` 칸에 공고 id 입력 (LH 임대는 건수가 많아 필요할 때만)
- SH는 첨부 내려받기 주소가 공개돼 있지 않아 대상이 아닙니다.
- `text_ok`가 false면 그림으로 된 PDF라 글을 뽑지 못한 것이고, `tables_missing`이 붙은 쪽은 표 없이 글만 뽑힌 쪽입니다.

- SH 공고문은 첨부를 직접 받을 수 없어, 미리보기 변환본의 쪽 그림을 받아 글자 인식(tesseract)으로 글만 남깁니다(`scripts/extract_sh_notice.py`, `engine` 이 `synap-preview-ocr`, `ocr: true`). 그림은 저장하지 않습니다. 기본 글은 4배 확대·선명화 후 tesseract(tessdata_best)로 읽어 `pages[].text` 에 두고, 금액 표로 보이는 쪽은 paddle(없으면 tesseract psm 11)로 다시 읽어 `pages[].table_text`·`amounts` 에 남기며 두 방식이 일치한 금액만 `pages[].amounts_checked` 에 담습니다. 글자 인식 결과라 표 안의 숫자가 틀릴 수 있으니 `amounts_checked` 밖의 금액은 원문을 확인해야 합니다.

## SH 주택정보 파일: `data/sh_houses.json`

공개 주소: https://revi404.github.io/sohyunrichlab/data/sh_houses.json · 출처: [SH 서울주택정보](https://www.i-sh.co.kr/houseinfo/main/mainPage.do)

| 묶음 | 내용 |
|---|---|
| `notices[]` | 진행 중인 모집공고 `title` `date` `complex_ids`(해당 단지 번호) `url` |
| `model_houses[]` | 사이버 모델하우스 `name` `type`(주택형) `url` |
| `complexes{단지 번호}` | `name` `addr` `supply`(재개발임대 등) `units` `heating` `corridor` `center`(관할 센터) `surroundings`(주변 환경 설명) |
| `complexes{}.types[]` | 주택형별 `exclusive_area`·`contract_area`(㎡) `households` `rooms` `deposit`·`rent`(원) `vacant`(공가) `waitlist`(예비자) `moved_out_1y`(최근 1년 퇴거) `as_of`(기준월) `floorplans[]`(평면도 이미지 주소) |
| `complexes{}.images[]` | 전경 등 단지 사진 주소 |

- 하루 한 번(03:40) 실행합니다. 진행 중 공고 단지와 사이버 모델하우스 단지를 먼저 읽고, 나머지 아파트 단지(813곳)는 하루 40곳씩 순서대로 읽어 약 3주에 한 바퀴를 돕니다. `progress`에 진행 상황이 있습니다.
- 이번 달에 이미 읽은 단지는 다시 읽지 않습니다(자료 기준이 월 단위).
- 이미지는 내려받지 않고 주소만 남깁니다. 보드에 직접 싣기 전에 SH 이용 조건을 확인해야 합니다.
- 속도를 바꾸려면 워크플로의 실행 줄에 `--batch 80`처럼 붙입니다.
