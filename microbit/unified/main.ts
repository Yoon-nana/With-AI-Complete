// AIGO IN: A=checking, B=exercise, A+B=nap/pause.
// Both original trained model blobs are preserved in models.ts.
namespace unifiedRunner {
    //% shim=mlrunner::deinit
    export function stop(): void { }
}
let mode = ""
let requestedMode = "CHECK"
let buttonRequested = false
let checkingStart = 0
let lastActivity = "UNKNOWN"
let lastExercise = 0
let lastCountAt = -10000
let cheeringCount = 0
let elbowCurlCount = 0
let wristCircleCount = 0
let warmUntil = 0
let modelChangedAt = 0
const checkWorking = new MlEvent(2, "working")
const checkStill = new MlEvent(3, "not working")
const exerciseRest = new MlEvent(2, "rest")
const exerciseCheering = new MlEvent(3, "cheering")
const exerciseElbow = new MlEvent(4, "elbow curl")
const exerciseWrist = new MlEvent(5, "wrist circle")

function requestMode(next: string, fromButton: boolean) {
    requestedMode = next
    buttonRequested = fromButton
}
input.onButtonPressed(Button.A, function () { requestMode("CHECK", true) })
input.onButtonPressed(Button.B, function () { requestMode("EXERCISE", true) })
input.onButtonPressed(Button.AB, function () { requestMode("NAP", true) })
serial.redirectToUSB()
serial.setBaudRate(BaudRate.BaudRate115200)
serial.onDataReceived(serial.delimiters(Delimiters.NewLine), function () {
    const command = serial.readUntil(serial.delimiters(Delimiters.NewLine)).trim()
    if (command == "MODE,CHECK") requestMode("CHECK", false)
    else if (command == "MODE,EXERCISE") requestMode("EXERCISE", false)
    else if (command == "MODE,NAP") requestMode("NAP", false)
    else if (command == "RESET,COUNTS") {
        cheeringCount = 0; elbowCurlCount = 0; wristCircleCount = 0
        lastExercise = 0; lastCountAt = -10000
        serial.writeLine("EX,0,0,0")
    }
})
function announce() { serial.writeLine("MODEL," + mode) }
function switchMode() {
    const next = requestedMode
    const notifyButton = buttonRequested
    buttonRequested = false
    unifiedRunner.stop()
    music.stopAllSounds()
    basic.clearScreen()
    checkingStart = 0; lastActivity = "UNKNOWN"; lastExercise = 0
    mode = next
    modelChangedAt = input.runningTime()
    music.setBuiltInSpeakerEnabled(mode != "NAP")
    if (mode == "CHECK") {
        ml.events = [ml.event.Unknown, checkWorking, checkStill]
        ml.getModelBlob = function () { return unifiedModels.checking }
        ml.startRunning()
        basic.showIcon(IconNames.StickFigure)
    } else if (mode == "EXERCISE") {
        ml.events = [ml.event.Unknown, exerciseRest, exerciseCheering, exerciseElbow, exerciseWrist]
        ml.getModelBlob = function () { return unifiedModels.exercise }
        ml.startRunning()
        basic.showString("E")
    } else {
        basic.showIcon(IconNames.Asleep)
    }
    warmUntil = input.runningTime() + 1500
    if (notifyButton) serial.writeLine("BUTTON," + mode)
    announce()
}
serial.writeLine("BOOT,UNIFIED")
serial.writeLine("CAPS,UNIFIED,1")
basic.forever(function () {
    if (requestedMode != mode) switchMode()
    const now = input.runningTime()
    if (mode == "CHECK") {
        let state = "UNKNOWN"
        if (now >= warmUntil) {
            if (ml.isDetected(checkWorking)) state = "MOVING"
            else if (ml.isDetected(checkStill)) state = "STILL"
        }
        if (state == "STILL") {
            if (lastActivity != "STILL") checkingStart = now
        } else checkingStart = 0
        const seconds = state == "STILL" ? Math.idiv(now - checkingStart, 1000) : 0
        if (state != lastActivity) {
            if (state == "MOVING") basic.showIcon(IconNames.StickFigure)
            else if (state == "STILL") basic.showIcon(IconNames.No)
            else basic.clearScreen()
        }
        lastActivity = state
        serial.writeLine("ML," + state + "," + seconds)
    } else if (mode == "EXERCISE") {
        let action = 0
        if (now >= warmUntil) {
            if (ml.isDetected(exerciseRest)) action = 1
            else if (ml.isDetected(exerciseCheering)) action = 2
            else if (ml.isDetected(exerciseElbow)) action = 3
            else if (ml.isDetected(exerciseWrist)) action = 4
        }
        if (action >= 2 && action != lastExercise && now - lastCountAt >= 900) {
            if (action == 2) cheeringCount += 1
            else if (action == 3) elbowCurlCount += 1
            else wristCircleCount += 1
            lastCountAt = now
            basic.showString(action == 2 ? "C" : action == 3 ? "E" : "W")
        }
        lastExercise = action
        serial.writeLine("EX," + cheeringCount + "," + elbowCurlCount + "," + wristCircleCount)
    }
    basic.pause(250)
})
basic.forever(function () {
    serial.writeLine("CAPS,UNIFIED,1")
    if (mode != "") announce()
    basic.pause(2000)
})
basic.forever(function () {
    if (mode == "CHECK" && checkingStart > 0 && input.runningTime() - checkingStart > 10000) {
        music.playTone(input.runningTime() - checkingStart > 20000 ? 988 : 523, 150)
    }
    basic.pause(1000)
})
