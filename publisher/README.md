# 단지 소개 글 자동 발행 (집 노트북용)

매일 정해진 시각에 노트북이 직접 브라우저를 띄워 **티스토리에 자세한 글 1편, 네이버 블로그에 요약 글 1편**을 올립니다.
글은 GitHub 이 매일 새로 만들어 두고(`scripts/build_complex_posts.py`), 이 프로그램은 아직 안 올린 단지를 순서대로 꺼내 씁니다.

| 블로그 | 글 | 순서 |
|---|---|---|
| 티스토리 sohyun-richlab | `posts/complex/<단지>.html` 표·평면도 전부 | `data/complex_posts.json` 의 `queue` |
| 네이버 sohyunrichlab | `posts/naver/<단지>.html` 질문형 요약, 평면도 전부 | `naver_queue` |

## 처음 한 번 설치

준비물: 파이썬 3.10 이상(윈도우는 python.org 설치 때 "Add to PATH" 체크), 크롬.

1. 이 저장소를 노트북에 내려받습니다. GitHub 저장소 화면 → Code → Download ZIP → 압축 풀기 (또는 `git clone`).
2. `publisher` 폴더에서
   - **윈도우**: `install_windows.bat` 더블클릭
   - **맥**: 터미널에서 `bash install_mac.sh`
3. 브라우저가 두 개 탭으로 열리면 **티스토리(카카오)와 네이버에 로그인**합니다. "로그인 상태 유지"를 꼭 켜 주세요. 끝나면 검은 창으로 돌아와 Enter.
4. 매일 올릴 시각을 입력하면 예약이 끝납니다.

## 첫 시험 (꼭 한 번)

실제로 올리기 전에 버튼 직전까지만 해 보고 화면을 확인합니다.

```
py publish.py tistory --dry-run     (맥은 python3)
py publish.py naver --dry-run
```

`shots/` 폴더의 사진에서 제목·본문·평면도가 제대로 들어갔는지 보고, 괜찮으면 `py publish.py all` 로 한 번 실제 발행해 봅니다.
시험 모드로 쓴 글은 임시저장으로 남을 수 있으니 블로그 관리 화면에서 지우면 됩니다.

## 매일 돌아가는 방식

- 예약 시각에 `publish.py all` 이 실행되고, 0~20분 사이 아무 때나 시작합니다(매일 같은 분에 올라가지 않게).
- 티스토리 → 네이버 순서로 각각 `config.json` 의 `*_per_run` 개수만큼 올립니다(기본 1편씩).
- 올린 글은 `state.json` 에 기록되어 다시 올라가지 않습니다. **이 파일은 지우지 마세요.**
- 실패하면 그 글은 기록하지 않고 다음 날 다시 시도합니다. 내용은 `publish.log`, 화면은 `shots/` 에 남습니다.
- 지금까지 몇 편 올렸는지: `py publish.py status`

**노트북이 켜져 있고 로그인(윈도우 계정)된 상태여야** 돌아갑니다. 덮개를 닫아 잠자기 상태면 그날은 건너뜁니다.

## 설정 `config.json`

| 항목 | 뜻 |
|---|---|
| `tistory_per_run` · `naver_per_run` | 한 번에 올릴 글 수. 0 이면 그 블로그는 쉼 |
| `tistory_enabled` · `naver_enabled` | `false` 면 그 블로그는 아예 안 올림 |
| `tistory_category` · `naver_category` | 올릴 카테고리 이름(비우면 기본 카테고리) |
| `gap_minutes` | 여러 편 올릴 때 글 사이 쉬는 시간(분, 최소~최대) |
| `start_delay_minutes` | 예약 시각 뒤 시작을 늦추는 범위(분) |

## 문제가 생기면

| 증상 | 할 일 |
|---|---|
| 로그상 "로그인이 풀렸습니다" | `py publish.py login` 다시 실행 |
| "글쓰기 화면을 찾지 못했습니다", 버튼 관련 실패 | 블로그 편집기 화면이 바뀐 경우입니다. `shots/` 의 오류 사진과 `publish.log` 를 Claude 에게 보내 주세요 |
| 네이버에 평면도가 안 보임 | `naver_image_wait_sec` 를 30 정도로 늘리기 |
| 예약을 끄고 싶음 | 윈도우: 작업 스케줄러에서 "SohyunRichlab Publish" 삭제 / 맥: `launchctl unload ~/Library/LaunchAgents/com.sohyunrichlab.publish.plist` |

## 주의

- 티스토리·네이버 모두 공식 글쓰기 API 가 없어 사람이 쓰는 화면을 그대로 조작합니다. 편집기 화면이 바뀌면 고쳐야 할 수 있습니다.
- 네이버는 짧은 시간에 많은 글을 기계적으로 올리면 저품질·제한을 걸 수 있으니 하루 1~2편을 넘기지 않는 것을 권합니다.
- 로그인 정보는 이 폴더의 `.profile/` 에만 저장되고 저장소에는 올라가지 않습니다(`.gitignore`).
