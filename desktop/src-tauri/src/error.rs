use serde::Serialize;

/// Every failure surfaced to the frontend. Serializes as `{ kind, message }` so
/// the UI can distinguish an auth problem (re-enter token) from a network one (retry).
#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("No API token stored for this account. Enter one on the Accounts screen.")]
    MissingToken,

    #[error("Qualtrics rejected the API token (401). Check the token and data center.")]
    Unauthorized,

    #[error("Qualtrics rate limit hit (429). Wait a moment and retry.")]
    RateLimited,

    #[error("Qualtrics error: {0}")]
    Api(String),

    #[error("Network error: {0}")]
    Network(String),

    #[error("{0}")]
    NotFound(String),

    #[error("Keychain error: {0}. On Linux this needs a running Secret Service (gnome-keyring or kwallet).")]
    Keychain(String),

    #[error("Config error: {0}")]
    Config(String),

    #[error("Import error: {0}")]
    Import(String),

    #[error("{0}")]
    Invalid(String),
}

impl AppError {
    fn kind(&self) -> &'static str {
        match self {
            AppError::MissingToken => "missing_token",
            AppError::Unauthorized => "unauthorized",
            AppError::RateLimited => "rate_limited",
            AppError::Api(_) => "api",
            AppError::Network(_) => "network",
            AppError::NotFound(_) => "not_found",
            AppError::Keychain(_) => "keychain",
            AppError::Config(_) => "config",
            AppError::Import(_) => "import",
            AppError::Invalid(_) => "invalid",
        }
    }

    /// True when retrying the same request could plausibly succeed.
    pub fn retryable(&self) -> bool {
        matches!(self, AppError::RateLimited | AppError::Network(_))
    }
}

impl Serialize for AppError {
    fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeStruct;
        let mut st = s.serialize_struct("AppError", 3)?;
        st.serialize_field("kind", self.kind())?;
        st.serialize_field("message", &self.to_string())?;
        st.serialize_field("retryable", &self.retryable())?;
        st.end()
    }
}

impl From<reqwest::Error> for AppError {
    fn from(e: reqwest::Error) -> Self {
        AppError::Network(e.to_string())
    }
}

impl From<std::io::Error> for AppError {
    fn from(e: std::io::Error) -> Self {
        AppError::Config(e.to_string())
    }
}

impl From<serde_json::Error> for AppError {
    fn from(e: serde_json::Error) -> Self {
        AppError::Config(format!("JSON: {e}"))
    }
}

pub type AppResult<T> = Result<T, AppError>;
