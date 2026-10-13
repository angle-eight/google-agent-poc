# 管理者用：Cloud Run + Agent Runtimeの準備・アクセス設定

[開発・デプロイ担当者向け手順](cloudrun-agent-runtime.md) と [公式CLIでのデプロイ手順](cli-deploy.md) を進めるために、管理者が行う作業をまとめています。コマンドはbash/zsh用です。既存リソースは再利用し、初回作成は省きます。

| タイミング | 管理者の作業 | 開発・デプロイ担当者の作業 |
| --- | --- | --- |
| Agent Runtimeだけを使う段階 | 課金・Runtime用API・IAM、Python方式のStorage用カスタムロール（手順1・2.1・3） | 専用devアカウントの認証と、ローカル・別サーバーからの利用 |
| Agent Runtimeデプロイ | 必要ならカスタム実行アカウントを準備（手順8） | Python方式ではバケットを作成し、エージェントを配置・確認。公式ADK CLI方式はステージングバケット不要 |
| Cloud Run移行時 | Cloud Run用API・追加IAM・Web/Buildアカウント・Secret（手順2.2・3.2・4・5） | 追加権限と準備を依頼し、Cloud Runへ配置 |
| Cloud Run初回デプロイ後 | 認証必須の確認とサービス単位のInvoker付与（手順6） | 画面・APIを配置し、管理者へ完了を連絡。その後プロキシで確認 |
| HTTPS URLの配布前 | IAPの有効化・利用者の許可（手順7） | `COOKIE_SECURE=true` へ更新し、ブラウザで確認 |
| 利用終了 | 専用ステージングバケット・Secret・実行アカウント・不要なIAM付与を削除（手順9） | Agent Runtime・Cloud Runを削除し、完了を連絡 |

## 1. 管理者の権限と作業環境

Ownerで実行できますが、Ownerが必須ではありません。各操作に必要な権限を既に持つ管理者が実行します。以下は対応する事前定義ロールの例で、開発・デプロイ担当者へ付与するロールとは別です。

| 管理作業 | 管理者側のロール例・付与先 |
| --- | --- |
| プロジェクトIAMの変更 | プロジェクトの `roles/resourcemanager.projectIamAdmin` |
| APIの有効化 | プロジェクトの `roles/serviceusage.serviceUsageAdmin` |
| Python方式のStorage用カスタムロールの作成・管理 | プロジェクトの `roles/iam.roleAdmin` |
| サービスアカウントの作成・削除と、そのIAM変更 | プロジェクトの `roles/iam.serviceAccountAdmin` |
| Secretの作成・版の追加・IAM変更・削除 | プロジェクトの `roles/secretmanager.admin` |
| Cloud Runの認証・サービスIAM設定 | プロジェクトの `roles/run.admin` |
| Cloud Run設定の更新・IAP有効化で既存イメージと実行IDを使う | 対象リポジトリの `roles/artifactregistry.reader` と、Webサービスアカウントの `roles/iam.serviceAccountUser` |
| 不要なコンテナイメージの削除（利用終了時） | 対象リポジトリの `roles/artifactregistry.repoAdmin` |
| Python方式の専用バケットのIAM変更・保存ファイルとバケットの削除 | 対象バケットの `roles/storage.admin`。開発者には付与しない |

プロジェクトIAMの変更には `resourcemanager.projects.getIamPolicy` と `resourcemanager.projects.setIamPolicy` が必要です。Project IAM AdminはAPI有効化やサービスアカウント作成までまとめて許可するロールではありません。[公式のプロジェクトIAM要件](https://docs.cloud.google.com/iam/docs/granting-changing-revoking-access)、[API有効化の要件](https://docs.cloud.google.com/run/docs/deploying-source-code)

開発者から共有されたAgent Runtime用の値を設定します。管理者はPython・uv・ADCの設定を行う必要はありません。Cloud Run用の変数・実行アカウント・Secretは移行時に手順4以降で準備します。

```bash
export ADMIN_EMAIL="admin@example.com"
export PROJECT_ID="your-project-id"
export DEPLOYER_EMAIL="dev@example.com"
export REGION="us-central1"
export STAGING_BUCKET="${PROJECT_ID}-agent-staging"
```

開発者と同じ端末を使う場合にも認証設定を混ぜないよう、管理者用の名前付きCLI構成を使います。次の作成コマンドは初回だけ実行します。

```bash
gcloud config configurations create helpdesk-admin --no-activate
```

続けて管理者のターミナルだけで構成を選び、ログインします。`CLOUDSDK_ACTIVE_CONFIG_NAME` はこのシェル内に適用され、開発者の別ターミナルの構成を切り替えません。

```bash
export CLOUDSDK_ACTIVE_CONFIG_NAME="helpdesk-admin"
gcloud auth login "$ADMIN_EMAIL"
gcloud config set account "$ADMIN_EMAIL"
gcloud config set project "$PROJECT_ID"
gcloud auth list --filter=status:ACTIVE --format='value(account)'
```

出力が管理者のメールアドレスであることを確認します。プロジェクトの課金が有効であることも確認してください。課金の関連付け権限は上のIAMロールとは別です。

## 2. 必要なAPIを有効にする

### 2.1 最初に実施：Agent Runtime用API

```bash
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

Agent Runtimeだけの段階では、このAPI準備と手順3までを実施します。Web/Buildアカウント・Secret・Cloud Runの準備は不要です。[Agent Runtimeの公式準備手順](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/setup)

### 2.2 Cloud Runへの移行時に追加するAPI

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  --project="$PROJECT_ID"
```

[Cloud Runのソースデプロイ](https://docs.cloud.google.com/run/docs/deploying-source-code) とSecretの保存に使うAPIです。IAP APIは必要な場合のみ手順7で有効にします。

## 3. 開発・デプロイ担当者へプロジェクトのロールを付与する

最初は次のAgent Runtime用ロールだけを付与します。ログ確認も行うためLogging Viewerを含めています。

```bash
for DEPLOYER_ROLE in \
  roles/aiplatform.user \
  roles/serviceusage.serviceUsageConsumer \
  roles/logging.viewer
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="user:$DEPLOYER_EMAIL" --role="$DEPLOYER_ROLE"
done
```

公式ADK CLI方式なら、ここで設定完了を担当者へ連絡し、CLI手順3.3以降へ進んでもらいます。Python方式なら次のStorage設定も行います。

### 3.1 Python方式のみ：Storageの権限を準備する

Cloud Runのロールなしで、担当者がバケットを作り、このリポジトリのSDKデプロイで必要な操作を行えるようにします。管理者が用途とスコープの異なる2つのカスタムロールを作成します。既存ロールが同じ権限で準備済みなら、作成を省きます。

```bash
gcloud services enable iam.googleapis.com --project="$PROJECT_ID"
gcloud iam roles create helpdeskBucketCreator \
  --project="$PROJECT_ID" --title="Helpdesk Bucket Creator" \
  --permissions=storage.buckets.create --stage=GA
gcloud iam roles create helpdeskStagingUploader \
  --project="$PROJECT_ID" --title="Helpdesk Staging Uploader" \
  --permissions=storage.buckets.get,storage.objects.create,storage.objects.get,storage.objects.list \
  --stage=GA
```

新規バケットを担当者が作る場合だけ、Creatorをプロジェクトに付与します。既存バケットを再利用する場合は不要です。

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="user:$DEPLOYER_EMAIL" \
  --role="projects/$PROJECT_ID/roles/helpdeskBucketCreator"
```

担当者へCreator付与完了を連絡し、[開発者用手順2.4](cloudrun-agent-runtime.md#24-ステージングバケットを作る担当者初回) でバケットを作ってもらいます。**作成完了の連絡を受けた後**、Uploaderをそのバケットにだけ付与します。既存バケットの場合はここから実施します。

```bash
gcloud storage buckets add-iam-policy-binding "gs://$STAGING_BUCKET" \
  --member="user:$DEPLOYER_EMAIL" \
  --role="projects/$PROJECT_ID/roles/helpdeskStagingUploader"
```

Uploader付与完了を担当者へ連絡し、バケット確認・Agent Runtimeデプロイへ進んでもらいます。このバケットIAMの変更は `storage.buckets.getIamPolicy/setIamPolicy` を持つ管理者が実行します。UploaderにはIAM変更・オブジェクト削除・バケット削除を含めません。

この権限構成は固定SDK 1.165.1のバケット取得、ファイルの新規保存と読み取りに合わせています。`scripts/deploy_agent.py` は毎回UUIDの異なる保存先を使うため、既存オブジェクトを上書きする権限を依頼していません。SDKやデプロイ処理を変更した際は必要な操作も再確認してください。[バケット作成の公式要件](https://docs.cloud.google.com/storage/docs/creating-buckets)、[カスタムロールの作成](https://docs.cloud.google.com/iam/docs/creating-custom-roles)、[固定SDKの実装](https://github.com/googleapis/python-aiplatform/blob/v1.165.1/agentplatform/_genai/_agent_engines_utils.py)

### 3.2 Cloud Run移行時だけ追加するロール

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="user:$DEPLOYER_EMAIL" --role=roles/run.sourceDeveloper
```

Web/Buildアカウントを使用する権限は手順4、Secretのメタデータ確認権限は手順5、Cloud Run Invokerはサービス作成後の手順6で付与します。Agent Runtime用の3ロールを再付与する必要はありません。

開発者への `roles/run.admin` やプロジェクトIAM管理ロールは付与しません。Cloud Run Invokerは、サービス作成後に手順6で対象サービスへ付与します。

## 4. Web・Buildサービスアカウントを準備する

**手順4〜7はCloud Runへ移行する場合だけ実施します。** 手順2.2・3.2を実施し、開発者と次の値をそろえます。

```bash
export SERVICE_NAME="helpdesk-web"
export SECRET_NAME="helpdesk-session-secret"
export SECRET_VERSION="1"
export WEB_SA="helpdesk-web@${PROJECT_ID}.iam.gserviceaccount.com"
export BUILD_SA="helpdesk-builder@${PROJECT_ID}.iam.gserviceaccount.com"
```

初回だけ作成します。既にある場合はIAM設定を確認し、作成を省きます。

```bash
gcloud iam service-accounts create helpdesk-web --project="$PROJECT_ID"
gcloud iam service-accounts create helpdesk-builder --project="$PROJECT_ID"
```

実行アカウントとビルドアカウントに必要なロールを付与し、担当者がその2つを使用できるようにします。

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$WEB_SA" --role=roles/aiplatform.user
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" --role=roles/run.builder

gcloud iam service-accounts add-iam-policy-binding "$WEB_SA" \
  --project="$PROJECT_ID" --member="user:$DEPLOYER_EMAIL" \
  --role=roles/iam.serviceAccountUser
gcloud iam service-accounts add-iam-policy-binding "$BUILD_SA" \
  --project="$PROJECT_ID" --member="user:$DEPLOYER_EMAIL" \
  --role=roles/iam.serviceAccountUser
```

| ID | 役割 |
| --- | --- |
| 開発・デプロイ担当者 | エージェント・Webの配置と動作確認 |
| `helpdesk-web` | Cloud RunからAgent Runtimeを呼び、Cookie署名鍵を読む |
| `helpdesk-builder` | Cloud Run用コンテナをビルドする |
| Agent Runtimeのデフォルトサービスエージェント | Runtime内でGeminiとマネージドセッションを使う。プラットフォームが自動作成・設定 |

`roles/iam.serviceAccountUser` はプロジェクト全体ではなく、対象のWeb・Buildサービスアカウントに付与します。[公式ビルドアカウント設定](https://docs.cloud.google.com/run/docs/configuring/services/build-service-account)、[Agent Runtimeの実行ID](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/setup#default-service-agent)

## 5. Cookie署名鍵のSecretを準備する

Cloud Run用のCookie署名鍵の生成にはOpenSSLを使います（Ubuntu/WSLでは `sudo apt-get install openssl`）。Agent Runtimeだけを使う場合、Secret Managerの準備は不要です。ローカルアプリ用の鍵は担当者が生成します。

初回だけランダムな署名鍵を生成して保存します。値をターミナルへ表示したり、開発者へ共有したりする必要はありません。

```bash
openssl rand -hex 32 | tr -d '\n' \
  | gcloud secrets create "$SECRET_NAME" \
      --project="$PROJECT_ID" --replication-policy=automatic --data-file=-
```

Web実行アカウントには値の読み取り、担当者にはメタデータ確認の権限を、対象Secretだけに付与します。既存Secretを再利用する場合もこの設定を確認します。

```bash
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --project="$PROJECT_ID" --member="serviceAccount:$WEB_SA" \
  --role=roles/secretmanager.secretAccessor
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --project="$PROJECT_ID" --member="user:$DEPLOYER_EMAIL" \
  --role=roles/secretmanager.viewer
gcloud secrets versions describe "$SECRET_VERSION" \
  --secret="$SECRET_NAME" --project="$PROJECT_ID" \
  --format='yaml(name,state)'
```

`state: ENABLED` を確認し、担当者へ **`PROJECT_ID`・`WEB_SA`・`BUILD_SA`・`SECRET_NAME`・数値の `SECRET_VERSION`・Cloud Run用の追加権限設定完了** を連絡します。担当者が開発者用手順5またはCLI手順7へ進める状態です。[Secret Managerのロール](https://docs.cloud.google.com/secret-manager/docs/access-control)

通常の更新では同じ鍵を使います。署名鍵を変更する場合だけ新しい版を追加し、出力の版番号を担当者へ連絡します。担当者はその版でCloud Runを更新します。旧Cookieが無効になり、新しい会話になります。

```bash
openssl rand -hex 32 | tr -d '\n' \
  | gcloud secrets versions add "$SECRET_NAME" \
      --project="$PROJECT_ID" --data-file=-
```

## 6. Cloud Run作成後にアクセスを設定する

担当者から初回デプロイの完了連絡を受けてから実行します。新規サービスはデフォルトで認証必須ですが、既存サービスを再利用する場合も設定を確認します。担当者のデプロイコマンドはIAMを変更しません。[Cloud Runの認証](https://docs.cloud.google.com/run/docs/authenticating/overview)

```bash
gcloud run services describe "$SERVICE_NAME" \
  --project="$PROJECT_ID" --region="$REGION" \
  --format='yaml(metadata.annotations,status.url,spec.template.spec.serviceAccountName)'
gcloud run services get-iam-policy "$SERVICE_NAME" \
  --project="$PROJECT_ID" --region="$REGION"
```

コンソールの **Cloud Run → 対象サービス → セキュリティ** で認証必須であることを確認します。Invoker IAMチェックが無効なら、管理者が次で有効にします。この設定更新には、手順1の対象イメージの読み取り権限とWeb実行アカウントを使用する権限も必要です。

```bash
gcloud run services update "$SERVICE_NAME" \
  --project="$PROJECT_ID" --region="$REGION" \
  --invoker-iam-check
```

サービスのIAMに `allUsers` または `allAuthenticatedUsers` のInvokerが残っている場合は、該当するコマンドだけ実行して解除します。プロジェクト・フォルダなどから広い呼び出し権限を継承している場合も、その付与元を確認してください。

```bash
gcloud run services remove-iam-policy-binding "$SERVICE_NAME" \
  --project="$PROJECT_ID" --region="$REGION" \
  --member=allUsers --role=roles/run.invoker
gcloud run services remove-iam-policy-binding "$SERVICE_NAME" \
  --project="$PROJECT_ID" --region="$REGION" \
  --member=allAuthenticatedUsers --role=roles/run.invoker
```

確認用の担当者に、対象サービス上のInvokerを付与します。他の利用者も許可する場合は `--member` をそのユーザーまたはグループに置き換えます。

```bash
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
  --project="$PROJECT_ID" --region="$REGION" \
  --member="user:$DEPLOYER_EMAIL" --role=roles/run.invoker
```

設定完了を担当者へ連絡し、[開発者用手順6.2](cloudrun-agent-runtime.md#62-認証付きプロキシでブラウザから開く) または [CLI手順7.4](cli-deploy.md#74-非公開のサービスをブラウザで開く) のプロキシ確認へ進んでもらいます。サービスを削除して作り直すとサービス単位のIAMも失われるため、その場合は再設定します。[Cloud Run IAM管理](https://docs.cloud.google.com/run/docs/securing/managing-access)

## 7. HTTPS URLを直接使う場合のIAP設定

ブラウザへCloud RunのHTTPS URLを渡す場合のみ設定します。担当者から対象サービスと利用を許可するユーザー・グループを受け取ります。管理者側には以下のロールが必要です。開発者には対象アプリの利用権限だけを付与します。

| 管理者側のロール | 付与先・用途 |
| --- | --- |
| `roles/run.admin` | プロジェクト。Cloud Runの認証設定 |
| `roles/iap.admin` | プロジェクト。IAPのアクセス権管理 |
| `roles/artifactregistry.reader` | 対象イメージのリポジトリ。設定変更時の再デプロイ |
| `roles/iam.serviceAccountUser` | Web実行アカウント。設定変更時の再デプロイ |
| `roles/iap.settingsAdmin` | プロジェクト。組織に属さないユーザーを許可する場合 |
| `roles/oauthconfig.editor` | プロジェクト。組織外または組織に属さないユーザーを許可する場合 |

1. IAP APIを有効にします。

   ```bash
   gcloud services enable iap.googleapis.com --project="$PROJECT_ID"
   ```

2. コンソールの **Cloud Run → 対象サービス → セキュリティ** で、認証を必須にして **Identity-Aware Proxy（IAP）** を有効にし、変更をデプロイします。コンソール経由ではIAPサービスエージェントへのInvoker付与も行われます。
3. IAPのポリシー編集で、担当者・利用者に **IAP-secured Web App User（`roles/iap.httpsResourceAccessor`）** を対象アプリ上で付与します。これは手順6のCloud Run Invokerとは別の利用権限です。
4. 組織に属さないプロジェクトや組織外ユーザーの場合は、コンソールの案内に従ってOAuth同意画面・OAuthクライアントを設定します。
5. 担当者へ設定完了を連絡し、[開発者用手順7](cloudrun-agent-runtime.md#7-cloud-runのurlをブラウザで直接使うiap) に従って `COOKIE_SECURE=true` へ更新し、HTTPS URLで確認してもらいます。

IAP有効化後はHTTPS URLで確認します。このアプリではIAPのユーザーIDと会話のユーザーIDの連携は実装していません。[公式IAP設定手順](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run)

## 8. 任意：Agent Runtimeの実行アカウントを指定する

デフォルトのサービスエージェントを使う場合は不要です。担当者から依頼された場合のみ専用アカウントを作り、担当者が使用できるようにします。

```bash
export AGENT_SA="helpdesk-agent@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud iam service-accounts create helpdesk-agent --project="$PROJECT_ID"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$AGENT_SA" --role=roles/aiplatform.user
gcloud iam service-accounts add-iam-policy-binding "$AGENT_SA" \
  --project="$PROJECT_ID" --member="user:$DEPLOYER_EMAIL" \
  --role=roles/iam.serviceAccountUser
```

担当者へ `$AGENT_SA` を伝え、Python方式では `AGENT_SERVICE_ACCOUNT` に設定してもらいます。Web・Buildアカウントとは別の実行IDです。[公式カスタム実行ID設定](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/setup#configure-agent-identity)

## 9. 利用終了時の管理者側の削除

担当者がAgent Runtimeと、配置した場合のみCloud Runを削除し、削除完了を確認した後に実行します。このPoC専用に作り、他のアプリが使っていないものだけが対象です。

Python方式の専用ステージングバケットは、管理者が保存ファイルとともに削除します。担当者が作成した実際のバケット名に `STAGING_BUCKET` を合わせてください。公式ADK CLI方式だけを使った場合は、この削除は不要です。担当者のStorage用カスタムロールにはバケット・オブジェクト削除権限がないため、管理者が対象バケットのStorage Adminなどで実行します。

```bash
gcloud storage rm --recursive "gs://$STAGING_BUCKET"
```

Cloud Run用のSecret・Web/Buildアカウントも準備した場合のみ、次も実行します。Agent Runtimeだけを使った場合は不要です。

```bash
gcloud secrets delete "$SECRET_NAME" --project="$PROJECT_ID"
gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$WEB_SA" --role=roles/aiplatform.user
gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$BUILD_SA" --role=roles/run.builder
gcloud iam service-accounts delete "$WEB_SA" --project="$PROJECT_ID"
gcloud iam service-accounts delete "$BUILD_SA" --project="$PROJECT_ID"
```

手順8のカスタム実行アカウントも作った場合は、そのプロジェクトIAM付与とアカウントを同様に削除します。今回だけ付与した開発者のプロジェクトロール（Python方式のBucket Creatorを含む）もIAM画面で解除します。手順3.1のカスタムロール自体もこのPoC専用なら、利用・付与が残っていないことを確認してIAMのロール画面で削除します。別の開発作業で使っているロールは維持してください。サービス・Secret・サービスアカウント・バケット単位のIAMは対象リソースの削除とともに失われます。

Artifact RegistryのイメージやCloud Buildの保存ソース・ログは、サービス削除だけではすべて消えません。不要なビルド成果物は担当者と確認して整理します。既存の共有リポジトリや、プラットフォームのサービスエージェントは削除しません。

2026-10-13に公式IAM要件とローカルのGoogle Cloud CLI実装を確認しています。この文書の作成では、実際のIAM変更・リソース作成・デプロイ・削除は実行していません。
