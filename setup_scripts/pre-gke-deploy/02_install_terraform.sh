

if command -v "terraform" &> /dev/null
then
    # This block runs if the command is found (exit code 0)
    echo "'terraform' is installed - aborting installation. Please first un-install terraform if you want to run this script from scratch."
    exit
else
    # This block runs if the command is NOT found (non-zero exit code)
    echo "'terraform' is not installed - installing..."
fi

sudo apt-get update && \
  sudo apt-get install\
   -y gnupg software-properties-common

wget -O- https://apt.releases.hashicorp.com/gpg | \
gpg --dearmor | \
sudo tee /usr/share/keyrings/hashicorp-archive-keyring.gpg > /dev/null

gpg --no-default-keyring \
--keyring /usr/share/keyrings/hashicorp-archive-keyring.gpg \
--fingerprint

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(grep -oP '(?<=UBUNTU_CODENAME=).*' /etc/os-release || lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list

sudo apt update

sudo apt-get install terraform
