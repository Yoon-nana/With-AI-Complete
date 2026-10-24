// CreateAI 홈트 횟수 기록기
// 데이터의 클래스 이름을 그대로 사용합니다:
// rest / cheering / elbow curl / wrist circle
//
// LED 표시 규칙:
// - CreateAI 분류 모드가 바뀌면 해당 약자만 표시 (R/C/E/W)
// - 횟수가 실제로 올라갈 때만 약자와 누적 횟수 표시 (예: C3)
// - 시작/휴식 안내 문구와 전체 횟수 표시는 하지 않습니다.
//
// 버튼:
// - B: A(cheering) -> E(elbow curl) -> W(wrist circle) 선택, 바뀐 약자 표시
// - A: 선택한 운동 횟수 +1, 약자와 누적 횟수 표시

let cheeringCount = 0
let elbowCurlCount = 0
let wristCircleCount = 0
let selectedAction = 0
let currentMode = ""

let lastCheeringAt = -10000
let lastElbowCurlAt = -10000
let lastWristCircleAt = -10000
let autoCountCooldownMs = 900

function showMode(code: string) {
    basic.showString(code)
}

function showCount(code: string, count: number) {
    basic.showString(code + count)
}

function addCheering(manual: boolean) {
    if (manual || input.runningTime() - lastCheeringAt >= autoCountCooldownMs) {
        cheeringCount += 1
        if (!manual) {
            lastCheeringAt = input.runningTime()
        }
        showCount("C", cheeringCount)
    }
}

function addElbowCurl(manual: boolean) {
    if (manual || input.runningTime() - lastElbowCurlAt >= autoCountCooldownMs) {
        elbowCurlCount += 1
        if (!manual) {
            lastElbowCurlAt = input.runningTime()
        }
        showCount("E", elbowCurlCount)
    }
}

function addWristCircle(manual: boolean) {
    if (manual || input.runningTime() - lastWristCircleAt >= autoCountCooldownMs) {
        wristCircleCount += 1
        if (!manual) {
            lastWristCircleAt = input.runningTime()
        }
        showCount("W", wristCircleCount)
    }
}

function showSelectedMode() {
    if (selectedAction == 0) {
        showMode("C")
    } else if (selectedAction == 1) {
        showMode("E")
    } else {
        showMode("W")
    }
}

// Rest는 모드만 표시하고 운동 횟수는 올리지 않습니다.
ml.onStart(ml.event.Rest, function () {
    showMode("R")
})

ml.onStart(ml.event.Cheering, function () {
    showMode("C")
    addCheering(false)
})

ml.onStart(ml.event.ElbowCurl, function () {
    showMode("E")
    addElbowCurl(false)
})

ml.onStart(ml.event.WristCircle, function () {
    showMode("W")
    addWristCircle(false)
})

// B를 누를 때마다 수동 카운트 대상 모드를 바꾸고 약자를 보여줍니다.
input.onButtonPressed(Button.B, function () {
    selectedAction = (selectedAction + 1) % 3
    showSelectedMode()
})

// A는 선택된 동작의 카운트를 1회 올립니다.
input.onButtonPressed(Button.A, function () {
    if (selectedAction == 0) {
        showMode("C")
        addCheering(true)
    } else if (selectedAction == 1) {
        showMode("E")
        addElbowCurl(true)
    } else {
        showMode("W")
        addWristCircle(true)
    }
})

// 전원을 켠 직후 LED는 비워 둡니다.
basic.clearScreen()
