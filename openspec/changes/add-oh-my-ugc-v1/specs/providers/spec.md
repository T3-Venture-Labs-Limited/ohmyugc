# Spec Delta

## Purpose

Connects oh-my-ugc to the AI services users already pay for (Replicate, fal, OpenRouter, ElevenLabs, Fish Audio) using their own keys, and turns every provider's job lifecycle and failure modes into one predictable behaviour.

## ADDED Requirements

### Requirement: Bring-your-own provider keys
The system SHALL let users store an API key for each supported provider (Replicate, fal, OpenRouter, ElevenLabs, Fish Audio) through the web app, the CLI or environment variables, with environment variables taking precedence. Keys SHALL be stored only on the user's machine and SHALL never be printed, logged, returned by an API response or written to an exported file; the app SHALL show only whether a key is set and its last four characters.

#### Scenario: Key saved in settings
- **WHEN** a user saves a Replicate key in settings
- **THEN** the settings view shows Replicate as connected with the key's last four characters, and no API response contains the full key

#### Scenario: Environment variable overrides stored key
- **WHEN** `REPLICATE_API_TOKEN` is set in the environment and a different key is stored in settings
- **THEN** jobs use the environment value and settings shows the key's source as the environment

#### Scenario: Key test
- **WHEN** a user presses "Test" next to a provider key
- **THEN** the system makes one free authenticated request and reports either "connected" or the provider's reason in plain English, without spending credit

### Requirement: Uniform job lifecycle
Every paid provider call SHALL go through one lifecycle: upload local inputs the provider needs, submit, poll (or receive a webhook) until a terminal state, and download every output into the project's local storage before the job is marked successful. Provider output URLs SHALL NOT be relied on after download.

#### Scenario: Successful job stores outputs locally
- **WHEN** an image-to-video job succeeds on any provider
- **THEN** the resulting video is saved inside the project folder and the job record points to the local file, not the provider URL

#### Scenario: Local input files are uploaded
- **WHEN** a job input is a local image, audio or video file
- **THEN** the system uploads it using that provider's file mechanism (or an inline data URI where the provider requires one) and passes the provider-side reference to the model

#### Scenario: Interrupted app resumes polling
- **WHEN** the app restarts while a submitted job is still running at the provider
- **THEN** the job resumes polling the existing provider job instead of submitting (and paying for) a new one

### Requirement: Rate limits and out-of-credit handling
The system SHALL respect provider rate limits by waiting for the provider's indicated retry time and retrying, and SHALL stop a job with a plain-English message when the provider reports insufficient credit or an invalid key. It SHALL NOT retry a request that the provider rejected as invalid input.

#### Scenario: Rate limited
- **WHEN** a provider responds with HTTP 429 and a retry delay
- **THEN** the system waits that long and retries, and the job shows "Waiting for <provider> rate limit" while it waits

#### Scenario: Insufficient credit
- **WHEN** a provider responds that the account has insufficient credit
- **THEN** the job fails with a message naming the provider and telling the user to add credit, and no automatic retry happens

#### Scenario: Invalid input is not retried
- **WHEN** a provider rejects a request as invalid (for example HTTP 422)
- **THEN** the job fails once with the provider's validation message and is not resubmitted

### Requirement: Official and community models on Replicate
The system SHALL run both Replicate official models (addressed by `owner/name`) and community models (which require a version identifier), resolving the version automatically when the user selects a community model by name.

#### Scenario: Community model by name
- **WHEN** a user selects a community background-removal model by `owner/name`
- **THEN** the job runs against that model's latest version without the user supplying a version id

### Requirement: Plain-English errors
Every provider failure shown to a user SHALL be a single plain sentence that names the provider and what to do next; raw response bodies SHALL be kept only in the job's detail log with any key material removed.

#### Scenario: Provider timeout
- **WHEN** a provider job stays in a non-terminal state past the model's configured time limit
- **THEN** the job fails with "<Provider> did not finish in N minutes. Try again or pick another model." and the provider job is cancelled where the provider supports it
