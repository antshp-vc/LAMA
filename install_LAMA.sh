# Install pip
sudo apt update
sudo apt install python3-pip

# Install LAMA
sudo pip3 install lama_phenotype_detection

# Install R
sudo apt install r-base

#  Install elastix
wget https://github.com/SuperElastix/elastix/releases/download/4.9.0/elastix-4.9.0-linux.tar.bz2
mkdir ~/elastix
tar xjf elastix-4.9.0-linux.tar.bz2 -C ~/elastix

home=~/
echo -e "\n# paths added by my LAMA installation" >> ~/.bashrc
echo "export LD_LIBRARY_PATH="$home"elastix/lib:\$LD_LIBRARY_PATH" >> ~/.bashrc
echo "export PATH="$home"elastix/bin:\$PATH" >> ~/.bashrc

