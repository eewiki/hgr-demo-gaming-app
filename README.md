# Custom Gaming App for Hand Gesture Recognition Demo

This application is part of the [Hand Gesture Recognition at the Edge for Game Control with the STM32N6](https://forum.digikey.com/t/hand-gesture-recognition-at-the-edge-for-game-control-with-the-stm32n6/70163) demo.

---

## Instructions

These instructions are for getting the application up and running on a Raspberry Pi 4 Model B with a fresh install of Raspberry Pi OS (64-bit). It should be possible to deploy on other platforms, but no others have been tested. 

1. Insert your SD card into the Pi and connect it to a monitor, mouse, and keyboard. Supply power and wait until it completely boots up. 

2. Establish an internet connection either through Wi-Fi or Ethernet. Access to the internet is required during setup to install dependencies, as well as when the application is launched. After the application is successfully launched, the internet connection may be disabled. 

3. Switch from Wayland to X11 using the raspi-config utility.

	a. Run the command `sudo raspi-config`
	
	b. Navigate to **Advanced Options** > **Wayland** and select *X11*. 
	
	c. Reboot when prompted. 

4. After the reboot is complete, open a terminal and clone the application repo.

```
git clone https://github.com/eewiki/hgr-demo-gaming-app.git
cd hgr-demo-gaming-app/
```

5. Install the application dependencies.

```
sudo apt install python3-pygame python3-serial python3-pynput xdotool
```

6. Run the application. It will take longer to start the first time it is run.

**NOTE:** If running the complete [Hand Gesture Recognition at the Edge for Game Control with the STM32N6](https://forum.digikey.com/t/hand-gesture-recognition-at-the-edge-for-game-control-with-the-stm32n6/70163) demo, be sure the STM32N6570-DK board (flashed with the [game controller application](https://github.com/eewiki/n6-ai-hand-landmarks-gesture-controller/tree/master)) is powered and plugged in at this time. 

```
python demo.py
```

7. Once the application is launched and the game pages are loaded, Fishy must be started manually. Navigate to the Fishy game (using CTRL + TAB) and press the large play button. Wait for the game to start, then press "PLAY". Use CTRL + TAB to navigate back to the main menu and begin interacting with the application as normal. 

**NOTE:** If any of the games fail to load for any reason, simply navigate back to the terminal (using CTRL + TAB), press CTRL + C to kill the application, and try running it again. 
