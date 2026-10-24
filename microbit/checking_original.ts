// 기존 학습이 들어 있는 CreateAI/MakeCode 프로젝트에서 사용하세요.
// 사용자가 준 코드는 유지하고 마지막에 시리얼 송신만 추가했습니다.
ml.onStart(ml.event.Working, function () {
    basic.showIcon(IconNames.StickFigure)
})
ml.onStart(ml.event.NotWorking, function () {
    basic.showLeds(`
        . . # . .
        . . # . .
        . . # . .
        . . . . .
        . . # . .
        `)
    while (ml.isDetected(ml.event.NotWorking)) {
        notexercisingtime += 1
        basic.pause(1000)
    }
})
input.onButtonPressed(Button.A, function () {
    basic.showNumber(exercisingtime / 1000)
})
ml.onStopDetailed(ml.event.NotWorking, function (duration) {
    basic.clearScreen()
    notexercisingtime = 0
})
ml.onStopDetailed(ml.event.Working, function (duration) {
    basic.clearScreen()
    exercisingtime += duration
})
let notexercisingtime = 0
let exercisingtime = 0
exercisingtime = 0
notexercisingtime = 0
basic.forever(function () {
    if (10 < notexercisingtime && notexercisingtime < 20) {
        music.play(music.stringPlayable("C C5 - - C C5 - - ", 80), music.PlaybackMode.UntilDone)
    }
    if (20 < notexercisingtime) {
        music.play(music.stringPlayable("C5 B C5 B C5 B C5 B ", 1000), music.PlaybackMode.UntilDone)
        basic.showLeds(`
            # . . . #
            . # . # .
            . . # . .
            . # . # .
            # . . . #
            `)
    }
    basic.pause(50)
})

// 여기부터 추가한 부분입니다.
// 기존 송신용 basic.forever는 삭제하고 이 송신부 하나만 사용하세요.
// 기존 ML 모델/LED/음악/변수는 변경하지 않습니다.
serial.setBaudRate(BaudRate.BaudRate115200)

basic.forever(function () {
    // X를 표시하는 기존 코드와 같은 카운터를 사용합니다.
    // 순간적인 분류 결과 때문에 X 표시 중 UNKNOWN을 보내지 않습니다.
    if (ml.isDetected(ml.event.Working)) {
        serial.writeLine("ML,MOVING,0")
    } else if (notexercisingtime > 0) {
        serial.writeLine("ML,STILL," + notexercisingtime)
    } else {
        serial.writeLine("ML,UNKNOWN,0")
    }
    basic.pause(250)
})
