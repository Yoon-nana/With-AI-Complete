// 기존 무활동 감시 본문은 그대로 두고 맨 뒤에 추가합니다.
serial.onDataReceived(serial.delimiters(Delimiters.NewLine), function () {
    let command = serial.readUntil(serial.delimiters(Delimiters.NewLine)).trim()
    if (command == "MODE,NAP") {
        music.stopAllSounds()
        music.setBuiltInSpeakerEnabled(false)
    } else if (command == "MODE,CHECK") {
        notexercisingtime = 0
        basic.clearScreen()
        music.setBuiltInSpeakerEnabled(true)
    }
})
basic.forever(function () {
    serial.writeLine("MODEL,CHECK")
    basic.pause(2000)
})
