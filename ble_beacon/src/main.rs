use std::time::Duration;

use bluer::adv::Advertisement;
use local_ip_address::local_ip;
use tokio::time::sleep;

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let session = bluer::Session::new().await.unwrap();
    let adapter = session.default_adapter().await.unwrap();
    adapter.set_powered(true).await.unwrap();
    let mut prev_ip_address = None;
    let mut handle = None;
    println!(
        "Advertising on Bluetooth adapter {} with address {}",
        adapter.name(),
        adapter.address().await.unwrap()
    );
    loop {
        let ip_address = local_ip();
        if handle.is_none() || Some(&ip_address) != prev_ip_address.as_ref() {
            println!("IP Adress: {:?}", ip_address);
            let ip_addr_str = match ip_address {
                Ok(ip_addr) => ip_addr.to_string(),
                Err(local_ip_address::Error::LocalIpAddressNotFound) => "no ip address".into(),
                Err(local_ip_address::Error::StrategyError(_)) => "IP addr error".into(),
                Err(local_ip_address::Error::PlatformNotSupported(_)) => unreachable!(),
            };
            let local_name = format!("ProjectIF ({ip_addr_str})");
            println!("Advertising with name: {local_name:?}");
            let le_advertisement = Advertisement {
                // Make it appear to be connectable so that people can check just from their Bluetooth settings instead of having a dedicated BLE scannign app such as nRF Connect
                advertisement_type: bluer::adv::Type::Peripheral,
                discoverable: Some(true),
                local_name: Some(local_name),
                // Generic computer appearance
                appearance: Some(128),
                ..Default::default()
            };
            prev_ip_address = Some(ip_address);
            handle = Some(adapter.advertise(le_advertisement).await.unwrap());
        }
        sleep(Duration::from_secs(1)).await;
    }
}
