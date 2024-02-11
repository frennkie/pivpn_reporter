# pivpn_vpnrpt
MQTT Reporting for PI VPN on Home Assistant

** I am not a pro and hacked this together through the good work of others, I would welcome feedback and help with improving this **

Purpose: report configured VPN clients on PiVPN to HomeAssistant via MQTT

How to use: assumes you already have an MQTT broker running and the appropiate configuration with Home Assistant set up. To use this, place the python script on your piVPN box, the run! Would be best setting a service to run this.

What it does: when running it effectively presents the ```pivpn -c``` command data to Home Assistance. Using discovery a device is created in HA representing piVPN instance and each configured client then is represented as an entity of that device.



```bash
sudo install -o root -g root -m 755 pivpn_reporter.py /usr/local/bin/pivpn_reporter.py

sudo install -o root -g root -m 600 pivpn_reporter.env /etc/pivpn_reporter.env
sudo install -o root -g root -m 644 pivpn_reporter.service /lib/systemd/system/pivpn_reporter.service
sudo systemctl daemon-reload
sudo systemctl enable pivpn_reporter.service
sudo systemctl start pivpn_reporter.service
sudo systemctl status pivpn_reporter.service
```


troubleshooting: `export $(grep -v '^#' /etc/pivpn_reporter.env | xargs) && env`