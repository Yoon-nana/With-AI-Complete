// 위쪽의 제공된 체조 카운팅 코드는 그대로 유지합니다.
serial.setBaudRate(BaudRate.BaudRate115200)
serial.writeLine("BOOT,EXERCISE")
serial.onDataReceived(serial.delimiters(Delimiters.NewLine), function () {
    let command = serial.readUntil(serial.delimiters(Delimiters.NewLine)).trim()
    if (command == "MODE,NAP") {
        music.stopAllSounds()
        music.setBuiltInSpeakerEnabled(false)
    } else if (command == "MODE,EXERCISE") {
        music.setBuiltInSpeakerEnabled(true)
    }
})
basic.forever(function () {
    serial.writeLine("EX," + cheeringCount + "," + elbowCurlCount + "," + wristCircleCount)
    basic.pause(250)
})
basic.forever(function () {
    serial.writeLine("MODEL,EXERCISE")
    basic.pause(2000)
})
