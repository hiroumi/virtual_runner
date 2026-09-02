# Phase 1 作業記録（表示キャリブレーター）

対象: Virtual Boy for Nintendo Switch アクセサリ向け立体視レーシングゲーム・プロトタイプ

## 2026-09-02: Phase 1 実装

- リポジトリを新規作成し、Phase 1（キャリブレーター）のみを実装。
  - `main.py` / `calibration.py` / `config.py` / `stereo_renderer.py`（Phase 2用の未実装プレースホルダー）
  - `requirements.txt`（pygame）/ `requirements-dev.txt`（+ pytest）
  - `tests/`（設定の保存・読込・不正値フォールバック・領域クランプ・全キー操作の自動テスト）
  - `README.md`（導入方法、起動方法、キー操作、実機確認手順、仮定事項を記載）
- 実機（Windows 11 + アクセサリ）が手元にないため、WSL上でSDLのダミードライバを使い、画面表示なしでの動作確認（`pytest` 10件、`--test-frames` によるスモークテスト）のみ実施。実際の見え方の確認はできていない状態で報告し、実機確認待ちとした。
- `config.json` は仮の初期値（left/right とも 280×200、画面中央付近に左右対称配置）とし、実機での調整前提であることをREADMEに明記。

## GitHub連携

- リポジトリ: https://github.com/hiroumi/virtual_runner
- 当初 `hiroumi/virutal_runner`（スペル違い）で試みたが404、`hiroumi/virtual_runner` としてPublicで作成し直し。
- SSH鍵の認証で問題が発生（`Permission denied (publickey)`）。原因は、登録した鍵が「Authentication Key」ではなく別種（Signing Key）として登録されていたこと。Authentication Keyとして登録し直してもらい、`ssh -T git@github.com` で認証成功（fingerprint `SHA256:uAlq38soKh+FHiZvcQQ/fi1uX7p0aMJ6Ea/eFxhyiEs` を確認）。
- Phase 1一式を初回コミットとしてpush済み（ブランチ: `master`）。

## 2026-09-02: 実機キャリブレーション実施

ユーザーが実機（Windows 11 + Virtual Boyアクセサリ + 7インチ 1024×600 HDMI液晶）でキャリブレーターを実行し、以下を確認：

- `ALIGNMENT` / `CROP` / `GRID` / `COLOR` の各テストモードを確認。
- `S`キーで `config.json` に保存。
- 再起動後も設定が復元されることを確認。

### 実機確認済みの値（このコミット時点の `config.json`）

```json
{
  "output_width": 1024,
  "output_height": 600,
  "fullscreen": false,
  "left_viewport": { "x": 152, "y": 175, "width": 280, "height": 282 },
  "right_viewport": { "x": 532, "y": 171, "width": 280, "height": 282 },
  "swap_eyes": false,
  "flip_left_h": false,
  "flip_left_v": false,
  "flip_right_h": false,
  "flip_right_v": false,
  "parallax_scale": 1.0,
  "content_scale": 1.0
}
```

- 左右の領域サイズは 280×282（幅は初期値のまま、高さのみ実機に合わせて 200→282 に調整）。
- 左右のY座標がわずかに異なる（175 / 171）。左右の光学位置の微妙なズレを垂直オフセットで補正した結果と考えられる。
- `swap_eyes` / `flip_*` はすべて `false` のまま。実機での見え方は入れ替え・反転とも不要だったと判断できる。
- `parallax_scale` / `content_scale` は初期値 `1.0` のまま。Phase 2で実際のゲーム視差量を検討する際に、必要であれば再調整する。

### 申し送り事項（Claude Codeより）

- `fullscreen` が `false`（ウィンドウ表示）のまま保存されている。キャリブレーション作業中はウィンドウ表示の方が都合が良かった可能性があるが、アクセサリを実際に覗いて遊ぶ際はフルスクリーン（`F`キー）が前提だった。この値のままで実機プレイに問題ないか、次回起動時に確認することを推奨。
- 今回の値はこのリポジトリのその他の設定（1024×600 / 60fps 前提）に対する、この個体のアクセサリ・この液晶パネル固有の調整結果。別の個体・別のパネルに置き換えた場合は再キャリブレーションが必要。

## 現在のステータス

Phase 1（キャリブレーター）は実機確認まで完了し、`config.json` をこのリポジトリにコミット済み。Phase 2（レーシングゲーム最小プロトタイプ）に着手可能な状態。
