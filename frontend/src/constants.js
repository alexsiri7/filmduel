// Must match CURRENT_PRIVACY_POLICY_VERSION in backend/routers/users.py: the backend
// rejects consent for any other version, and re-prompts users whose stored version
// differs. backend/tests/test_consent.py pins the two together.
export const CURRENT_PRIVACY_POLICY_VERSION = "2.1";
