# Anonymous source publication

## What is public and what stays local?

Publish source code, synthetic tests, public configuration examples, dependency files, CI, MIT license and generic documentation. Do not publish actual `config.json`, manual overrides, XML exports, music, reports, logs, SQLite caches, private screenshots, an original personal specification, `.venv`, bytecode or old Git history.

The working directory may still contain private files so its owner can continue using the audit. `.gitignore` excludes the standard runtime locations. The stronger publication boundary is `scripts/prepare_release.py`: it copies **only an explicit allowlist**, checks public text for common credential/home-path markers, and creates a clean directory and ZIP. It never copies private runtime directories, even if they exist next to the source.

The ZIP uses fixed timestamps and generic file permissions, not original file owners/timestamps. `PUBLIC_MANIFEST.json` contains only relative public filenames and hashes. No original Git metadata, remote URLs, author information or account information is copied. The script does not create a repository or push anything.

## Build and inspect the bundle

From the project directory:

```text
python scripts/prepare_release.py
```

The first run creates `dist/music-library-audit/` and `dist/music-library-audit.zip`. Subsequent runs create numbered siblings rather than deleting or overwriting an existing export. Use the paths printed by the script. The allowlist is in the script so a future maintainer can review every permitted file.

Inspect the file list and the generated manifest. Read changed documentation/source as well as running automated checks: a pattern scanner cannot establish anonymity of arbitrary prose. Test from the clean directory to verify the project does not depend on local settings:

```text
cd dist/music-library-audit
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
```

There should be no real XML, report, cache, settings or account key in the bundle. The tests create their own temporary synthetic files. Test bytecode and any newly created environments are ignored by Git.

## Prepare Git locally

Start in the clean exported directory, not the private working directory. Choose the author name and email you intend to disclose before committing. The placeholders below must be replaced; use repository-local settings so other projects are unaffected:

```text
git init -b main
git config user.name "PUBLIC_AUTHOR_NAME"
git config user.email "PUBLIC_EMAIL_OR_NOREPLY"
git add .
git diff --cached --name-only
git diff --cached
git commit -m "Initial public release"
```

Review the staged content before the commit. `.gitignore` cannot erase a private file that was already committed in some other repository; the clean export intentionally contains no such history.

A GitHub `noreply` email hides a personal email address but still links commits to the associated GitHub account. Publishing to an existing personal account may identify the publisher through the account itself, regardless of anonymous code. See [GitHub's email-address privacy reference](https://docs.github.com/en/account-and-profile/reference/email-addresses-reference). Decide account and author identity separately; this project does not configure them automatically.

## Publish when ready

Create an empty repository on the GitHub account you choose, without initializing another README/license there. Then, from the clean local repository:

```text
git remote add origin REPOSITORY_URL
git push -u origin main
```

Replace `REPOSITORY_URL` with the intended destination. Do not paste tokens into source, documentation or committed URLs. Use your normal authenticated Git credential mechanism. These commands are instructions for the owner; the release exporter does not execute them.

Open the Actions tab and verify all six native Windows/macOS/Ubuntu and Python-version jobs. CI uses only synthetic data and read-only repository permissions; it publishes no private workbook artifact. Review failures before labeling the release cross-platform verified. The application is not an official Apple product.

The MIT license uses generic contributor attribution. Project metadata contains no author email, personal home path or repository/account URL. Dependency lock URLs and hashes identify public packages, not a user's music or credentials.
