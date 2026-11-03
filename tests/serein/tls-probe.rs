//! Build as an example in the prepared Serein workspace, using its exact dependencies.
//! The second URL must be a running local HTTPS fixture with a self-signed certificate.
use std::time::Duration;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let urls: Vec<_> = std::env::args().skip(1).collect();
    assert_eq!(urls.len(), 2, "Usage: termux-tls TRUSTED_URL SELF_SIGNED_URL");
    let client = reqwest::Client::builder()
        .https_only(true)
        .timeout(Duration::from_secs(20))
        .build()?;
    let response = client.get(&urls[0]).send().await?.error_for_status()?;
    assert!(response.status().is_success());
    let error = client
        .get(&urls[1])
        .send()
        .await
        .expect_err("a self-signed server certificate must not be accepted");
    assert!(
        format!("{error:?}").contains("UnknownIssuer"),
        "Expected a certificate trust error, got: {error:?}"
    );
    println!("TLS passed: system CA roots accepted; self-signed certificate rejected");
    Ok(())
}
