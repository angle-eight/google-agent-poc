# インストールからデプロイまで

公式CLIでデプロイを学ぶ場合は [CLIでデプロイする：Agent Runtime + Cloud Run](cli-deploy.md) を使ってください。`gcloud`・`adk deploy agent_engine`・`curl` で進める手順です。この文書のAgent Runtimeデプロイは独自Pythonスクリプトを使う方式です。

実行順は **依存関係のインストール → Google Cloudの準備 → ローカルでGeminiを確認 → Agent Runtimeへデプロイ → 必要なら画面をCloud Runへデプロイ** です。コマンドはbash/zsh用で、アプリ関連のコマンドはリポジトリのルートで実行します。

ローカルでの動作確認が済んでいて、Cloud RunとAgent Runtimeの両方を使う場合は、[ローカル確認後のデプロイ手順](cloudrun-agent-runtime.md)を使ってください。クラウドの準備から順に進める専用手順と、ブラウザからURLを直接開くためのIAP設定をまとめています。

専用devアカウントを使い、管理者と作業を分担する場合は、[開発・デプロイ担当者用手順](cloudrun-agent-runtime.md) と [管理者用手順](cloudrun-agent-runtime-admin.md) を使ってください。この文書の後半には管理者による初回作業も含まれています。

## 1. ソフトウェアをインストール

uvが未導入なら、macOS/Linuxでは次を実行し、新しいターミナルを開きます。[uv公式手順](https://docs.astral.sh/uv/getting-started/installation/)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Google Cloud CLIは[公式手順](https://docs.cloud.google.com/sdk/docs/install-sdk)でOSに対応する版を入れます。Linux x86_64では、リポジトリ外のインストール用ディレクトリで以下を実行できます。macOS・ARMでは公式ページの対応するアーカイブを選びます。

```bash
curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-linux-x86_64.tar.gz
tar -xf google-cloud-cli-linux-x86_64.tar.gz
./google-cloud-sdk/install.sh
```

新しいターミナルで `uv --version`、`gcloud --version` が実行できることを確認します。Dockerはローカルでコンテナを試す場合のみ必要です。Cloud Runの `--source` デプロイではCloud Buildがビルドするため、手元のDockerは不要です。[公式ソースデプロイ](https://docs.cloud.google.com/run/docs/deploying-source-code)

リポジトリのルートに戻ります。

```bash
uv python install 3.13
uv sync --locked --group dev
cp .env.example .env
```

既存の `.env` がある場合はコピーせず、その設定を使ってください。既定の `APP_BACKEND=local` はGoogle Cloudの設定と認証が必要です。次の手順で準備し、手順3で起動します。uvのキャッシュが書き込み禁止の環境では、コマンドの前に `UV_CACHE_DIR=/tmp/google-agent-poc-uv-cache` を付けてください。

## 2. Google Cloudの準備

Google Cloudコンソールでプロジェクトを作成または選択し、課金を有効にします。[Agent Runtime公式セットアップ](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/setup?hl=ja)

以下の `your-project-id` と `you@example.com` を実際の値に置き換えます。`STAGING_BUCKET` は世界全体で一意の名前にしてください。

```bash
export PROJECT_ID="your-project-id"
export REGION="us-central1"
export STAGING_BUCKET="${PROJECT_ID}-agent-staging"
export DEPLOYER_EMAIL="you@example.com"

gcloud auth login
gcloud config set project "$PROJECT_ID"
gcloud auth application-default login
gcloud auth application-default set-quota-project "$PROJECT_ID"

gcloud services enable \
  aiplatform.googleapis.com \
  storage.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  cloudtrace.googleapis.com \
  telemetry.googleapis.com \
  cloudresourcemanager.googleapis.com \
  --project="$PROJECT_ID"
```

`gcloud auth login` はCLI用、`application-default login` はPython SDK用です。両方を設定します。サービスアカウントのJSON鍵を作成する必要はありません。

### 必要な権限

API有効化・IAM変更・バケット作成を行える管理者が初期設定を行います。組織管理のプロジェクトでは管理者に設定を依頼してください。

| 利用者 / アカウント | 権限・ロール | 用途 |
| --- | --- | --- |
| 初期設定者 | Service Usage Admin、IAM変更権限、Storage Admin | APIの有効化、権限設定、バケット作成 |
| 開発・Agent Runtimeデプロイ者 | `roles/aiplatform.user` | モデル利用、エージェントの管理と呼び出し |
| 開発者 | `roles/serviceusage.serviceUsageConsumer` | ADCの課金先プロジェクトの利用 |
| デプロイ者 | ステージングバケット上の `roles/storage.admin` | SDKによるアーティファクトの保存 |
| Agent Runtimeのデフォルトサービスエージェント | 自動付与の `roles/aiplatform.reasoningEngineServiceAgent` | ランタイムとモデルの実行 |

管理者が開発者にロールを設定する例です。

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="user:$DEPLOYER_EMAIL" --role=roles/aiplatform.user
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="user:$DEPLOYER_EMAIL" --role=roles/serviceusage.serviceUsageConsumer

gcloud storage buckets create "gs://$STAGING_BUCKET" \
  --project="$PROJECT_ID" --location="$REGION" \
  --uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding "gs://$STAGING_BUCKET" \
  --member="user:$DEPLOYER_EMAIL" --role=roles/storage.admin
```

このサンプルでは、エージェントはデフォルトのマネージドサービスエージェントを利用します。独自のサービスアカウントを使う場合は、`AGENT_SERVICE_ACCOUNT` にメールアドレスを設定し、そのアカウントに `roles/aiplatform.user`、デプロイ者にそのアカウントの `roles/iam.serviceAccountUser` を付与します。[公式ID・権限設定](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/setup?hl=ja#configure-agent-identity)

`REGION` はAgent Runtimeの場所です。モデル側の接続先 `MODEL_LOCATION=global` とは別です。初期値の `us-central1` は[Agent Runtime対応リージョン](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-locations?hl=ja)です。`global` はモデルの処理先を日本に限定する設定ではありません。

## 3. ローカルで実際のGeminiを呼ぶ

`.env` を編集します。シェルの環境変数が存在する場合は、そちらが `.env` より優先されます。

```dotenv
APP_BACKEND=local
GOOGLE_CLOUD_PROJECT=実際のプロジェクトID
GOOGLE_CLOUD_LOCATION=us-central1
MODEL_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=true
GEMINI_MODEL=gemini-3.5-flash
GOOGLE_CLOUD_STAGING_BUCKET=gs://実際のステージングバケット名
COOKIE_SECURE=false
```

```bash
uv run --locked python main.py
```

http://localhost:8080 で「VPNに接続できない」「税込18万円のPCを2台購入したい」などを入力します。画面のモード表示が **ADK + Gemini** になっていることを確認します。続けて「直らなかったら？」と質問し、会話の文脈が引き継がれることを確認します。

CLIからも確認できます。

```bash
uv run --locked python -m scripts.query_agent 'VPNに接続できません'
```

ADK標準の開発UIを使う場合は `uv run --locked adk web . --port 8000` で起動し、`helpdesk` を選びます。標準UIは開発用として手元で使用します。

`helpdesk` は受付とIT・人事・経理の3担当からなるチームです。担当の振り分け、検索対象、ADK Webでのイベント確認は [READMEのエージェントチーム](../README.md#エージェントチームとadk-webでの確認) を参照してください。例えば同じ会話でPC購入→有給休暇→出張費の順に質問すると、担当から受付へ戻る引き継ぎも確認できます。

## 4. Agent Runtimeへエージェントをデプロイ

このサンプルは **ADKオブジェクトをシリアライズし、Cloud Storageにステージングする方式** です。[公式デプロイ方法](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent?hl=ja)

設定を先に確認できます。dry-runはGoogleへ接続しません。

```bash
uv run --locked python -m scripts.deploy_agent --dry-run
uv run --locked python -m scripts.deploy_agent
```

処理には数分かかることがあります。デプロイ時には規程JSON・ツール・チームの定義も送られます。Pythonコード、規程JSON、画面の静的ファイルを明示して同梱し、ADK Webの会話DB・成果物（`.adk/`）、`.env`、認証情報、Cookieの秘密鍵は送られません。予約済みの `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` もランタイムの環境変数として指定せず、プラットフォームの設定を使います。

成功すると `.deploy/agent.json` と、次の形式のリソース名が出力されます。

```text
projects/123456789/locations/us-central1/reasoningEngines/987654321
```

ブラウザを区別するCookieの署名鍵を生成します。

```bash
uv run --locked python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

出力された値とリソース名を `.env` に設定します。

```dotenv
APP_BACKEND=remote
AGENT_ENGINE_RESOURCE_NAME=projects/123456789/locations/us-central1/reasoningEngines/987654321
SESSION_SECRET=生成した32文字以上の秘密の値
COOKIE_SECURE=false
```

```bash
uv run --locked python main.py
```

http://localhost:8080 のモード表示が **Agent Runtime** に変わり、質問に回答すれば、クラウド上のエージェントに接続できています。画面をCloud Runへデプロイしなくても、この状態で利用できます。

remoteのCLIで同じ会話を継続する例です。1回目に出力される `session_id` を2回目に指定します。

```bash
uv run --locked python -m scripts.query_agent 'VPNに接続できない' --user-id smoke-user
uv run --locked python -m scripts.query_agent '直らなかったら？' \
  --user-id smoke-user --session-id '1回目のsession_id'
```

## 5. 画面をCloud Runにデプロイ（任意）

エージェントのリソース名をシェルにも設定します。以降のIAM・Secret作成は管理者権限で実行します。

```bash
export AGENT_RESOURCE="projects/123456789/locations/us-central1/reasoningEngines/987654321"
export WEB_SA="helpdesk-web@${PROJECT_ID}.iam.gserviceaccount.com"
export BUILD_SA="helpdesk-builder@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com --project="$PROJECT_ID"

gcloud iam service-accounts create helpdesk-web --project="$PROJECT_ID"
gcloud iam service-accounts create helpdesk-builder --project="$PROJECT_ID"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$WEB_SA" --role=roles/aiplatform.user
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" --role=roles/run.builder
```

Cloud Run用アカウントはAgent Runtimeを呼び出します。ビルド用アカウントはCloud Buildでコンテナを作ります。[公式ソースデプロイ権限](https://docs.cloud.google.com/run/docs/deploying-source-code)

デプロイ者に、Cloud Runのソースデプロイ権限、両サービスアカウントの使用権限、画面へのアクセス権限を付与します。

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="user:$DEPLOYER_EMAIL" --role=roles/run.sourceDeveloper
gcloud iam service-accounts add-iam-policy-binding "$WEB_SA" \
  --project="$PROJECT_ID" --member="user:$DEPLOYER_EMAIL" --role=roles/iam.serviceAccountUser
gcloud iam service-accounts add-iam-policy-binding "$BUILD_SA" \
  --project="$PROJECT_ID" --member="user:$DEPLOYER_EMAIL" --role=roles/iam.serviceAccountUser
```

Cookieの署名鍵はSecret Managerに保存します。初回作成の例です。既にSecretがあれば `gcloud secrets versions add` で版を追加し、デプロイ時の版番号も合わせます。

```bash
mkdir -p .deploy
uv run --locked python -c 'import secrets; print(secrets.token_urlsafe(32), end="")' > .deploy/session-secret.txt
gcloud secrets create helpdesk-session-secret --project="$PROJECT_ID" \
  --replication-policy=automatic --data-file=.deploy/session-secret.txt
gcloud secrets add-iam-policy-binding helpdesk-session-secret --project="$PROJECT_ID" \
  --member="serviceAccount:$WEB_SA" --role=roles/secretmanager.secretAccessor
```

アップロード後の `.deploy/session-secret.txt` は不要になれば削除します。`.deploy` と `.env` はGit・Cloud Runのソースアップロードから除外しています。

以下は認証設定も行うため、`run.services.setIamPolicy` 権限を持つ管理者（例: `roles/run.admin`）が実行してください。通常のソース更新には先に付与したSource Developer権限を使用できます。[公式IAM要件](https://docs.cloud.google.com/run/docs/securing/managing-access)

```bash
gcloud run deploy helpdesk-web \
  --project="$PROJECT_ID" --region="$REGION" \
  --source=. \
  --service-account="$WEB_SA" \
  --build-service-account="projects/$PROJECT_ID/serviceAccounts/$BUILD_SA" \
  --no-allow-unauthenticated \
  --min-instances=0 --max-instances=2 \
  --memory=1Gi --cpu=1 --timeout=180 \
  --set-env-vars="APP_BACKEND=remote,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$REGION,AGENT_ENGINE_RESOURCE_NAME=$AGENT_RESOURCE,COOKIE_SECURE=false" \
  --set-secrets="SESSION_SECRET=helpdesk-session-secret:1"
```

このコマンドはDockerfileをCloud Buildでビルドします。認証が必要なCloud Runサービスとして作成します。[gcloud run deploy公式リファレンス](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy)

管理者が利用者にサービス単位のInvoker権限を付与し、認証付きのローカルプロキシで開きます。

```bash
gcloud run services add-iam-policy-binding helpdesk-web \
  --project="$PROJECT_ID" --region="$REGION" \
  --member="user:$DEPLOYER_EMAIL" --role=roles/run.invoker
gcloud run services proxy helpdesk-web \
  --project="$PROJECT_ID" --region="$REGION" --port=8080
```

ブラウザで http://localhost:8080 を開きます。URLの直接アクセスにはCloud Run IAMの認証が必要です。[公式アクセス制御](https://docs.cloud.google.com/run/docs/securing/managing-access)

この手順ではHTTPのローカルプロキシに合わせて `COOKIE_SECURE=false` にしています。HTTPSで直接利用する認証付きの経路を用意したら、`COOKIE_SECURE=true` に変更してください。プロキシコンポーネントが不足している場合は、アーカイブ版CLIでは `gcloud components install cloud-run-proxy`、apt版では `sudo apt-get install google-cloud-cli-cloud-run-proxy` を使います。

手元でコンテナからAgent Runtimeへの接続を確認する場合は、手順4で `.env` にリソース名と `SESSION_SECRET` を設定したうえで実行します。Linux/WSLでは、手元のADCファイルをマウントし、そのファイルを読めるユーザーで起動します。

```bash
docker build -t helpdesk-poc .
docker run --rm --user "$(id -u):$(id -g)" \
  -p 8765:8080 --env-file .env \
  -e APP_BACKEND=remote -e COOKIE_SECURE=false \
  -e GOOGLE_APPLICATION_CREDENTIALS=/tmp/google-adc.json \
  --mount "type=bind,src=$HOME/.config/gcloud/application_default_credentials.json,dst=/tmp/google-adc.json,readonly" \
  helpdesk-poc
```

http://localhost:8765 を開いて質問します。Cloud Runでは実行サービスアカウントを使うため、このADCマウントは不要です。

## 6. 更新・動作確認

規程JSON、ツール、指示、モデル設定を変更したら、テストしてエージェントを更新します。

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
uv run --locked python -m scripts.deploy_agent --update "$AGENT_RESOURCE"
```

画面・API・規程JSONを変更した場合は、Cloud Runのデプロイコマンドも再実行します。規程JSONはエージェントとWebアプリの両方に含まれるため、両方を更新して参照表示を揃えてください。remoteの画面で `GEMINI_MODEL` を変更するだけではクラウド上のエージェントのモデルは変わりません。

確認する質問と期待する動作:

| 質問 / 操作 | 期待する動作 |
| --- | --- |
| VPNに接続できない | VPN手順とIT-001を参照 |
| 税込18万円のPCを2台購入 | 360,000円、上長と部門責任者、IT-002 |
| 税込10万円のPCを2台購入 | 200,000円、上長のみ |
| 有給休暇は何日前までに申請？ | 人事担当、原則3営業日前、HR-002 |
| 国内出張のホテル代の上限は？ | 経理担当、1泊税込12,000円、FIN-002 |
| 同じ会話でPC購入→有給→出張を相談 | 担当→受付→次の担当と切り替わる。画面の「担当」表示で確認 |
| 退職金について教えて | 同梱規程に情報がないと回答 |
| 別のブラウザで開く | 他のブラウザの会話を継続できない |
| 新しい会話 | 現在のセッションを削除して新しい相談を開始 |

モデルの回答は毎回同じ文面になるとは限りません。初期モデルと接続先は[Gemini 3.5 Flash公式仕様](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash)で確認しています。モデル変更時は[ライフサイクル](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions)と提供リージョンを確認してください。

## 7. よくある問題

| 症状 | 確認すること |
| --- | --- |
| `Temporary failure in name resolution` | [DNS・実行環境の疎通確認](cloudrun-agent-runtime.md)。通常のターミナルで接続できるか比較 |
| 画面のモードが設定と違う | `.env` のAPP_BACKEND、シェル変数の優先、サーバー再起動 |
| ADCが見つからない | `gcloud auth application-default login` |
| 403 / PERMISSION_DENIED | 利用者・実行サービスアカウントのaiplatform.user、API有効化、課金、組織ポリシー |
| モデル404 | GEMINI_MODELとMODEL_LOCATIONの組み合わせ、モデルの提供終了、プロジェクトでの利用可否 |
| ステージングで403 | バケットの存在とデプロイ者の権限。同一プロジェクトのバケットを利用 |
| カスタムエージェントSAでデプロイ失敗 | デプロイ者のserviceAccountUser、実行SAのaiplatform.user |
| Cloud Build失敗 | 指定したBUILD_SAのrun.builderとデプロイ者のserviceAccountUser、ビルドログ |
| Cloud Run起動失敗 | リソース名、project/location、Secretの版番号、WEB_SAのSecretアクセス権限 |
| remoteで会話404 | 同じCookie・user_idで利用。localは再起動すると消える。新しい会話を開始 |
| プロキシで会話が毎回切れる | COOKIE_SECURE=false、全インスタンス共通のSESSION_SECRET、Cookie許可 |
| 8080番ポートが使用中 | `PORT=8765 uv run --locked python main.py` |

Cloud Runログは `gcloud run services logs read helpdesk-web --project="$PROJECT_ID" --region="$REGION"` で確認します。ブラウザにはSDKの詳細エラーや認証情報を返しません。

## 8. 料金と削除

local / remoteはモデル料金、クラウドデプロイ後はAgent Runtime・Cloud Run・Storage・ビルド・Secret Managerなどの料金が関係します。最小インスタンスを0、最大を2にしていますが、これは利用額の上限ではありません。試用プロジェクトには予算通知を設定し、利用後に削除してください。[Google Cloud料金](https://cloud.google.com/pricing)

以下はこのPoCのリソースを削除するコマンドです。バケットのコマンドは中のアーティファクトも削除します。共有リソースには実行しないでください。

```bash
uv run --locked python -m scripts.delete_agent "$AGENT_RESOURCE"
gcloud run services delete helpdesk-web --project="$PROJECT_ID" --region="$REGION"
gcloud storage rm --recursive "gs://$STAGING_BUCKET"
gcloud secrets delete helpdesk-session-secret --project="$PROJECT_ID"
gcloud iam service-accounts delete "$WEB_SA" --project="$PROJECT_ID"
gcloud iam service-accounts delete "$BUILD_SA" --project="$PROJECT_ID"
```

Agent Runtimeの削除は非同期です。コンソールで完了を確認します。Cloud Runソースデプロイで作られたArtifact Registryのイメージ、Cloud Buildの保存ソース・ログも不要ならコンソールで整理します。PoC専用プロジェクトを丸ごと廃棄する場合は、プロジェクト削除でもまとめて片付けられます。

2026-10-07時点の公式ドキュメントとインストールしたSDKを基に作成しています。Google Cloudへの実際の接続・デプロイは、利用するプロジェクトで上記の確認を実施してください。
