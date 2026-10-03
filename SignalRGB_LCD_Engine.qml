import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    anchors.fill: parent
    property bool loadingCaptureState: false

    function readCaptureState() {
        var request = new XMLHttpRequest()
        request.open("GET", "http://127.0.0.1:41722/config")
        request.onreadystatechange = function() {
            if (request.readyState === XMLHttpRequest.DONE && request.status === 200) {
                try {
                    var state = JSON.parse(request.responseText)
                    loadingCaptureState = true
                    captureSwitch.checked = false
                    captureStatus.text = "Canvas-Erfassung nicht verfügbar: Third Party Services erhalten kein device.color(). Dafür wäre ein separates Geräteplugin nötig."
                    loadingCaptureState = false
                } catch (error) {
                    captureStatus.text = "Helper-Antwort konnte nicht gelesen werden"
                }
            } else if (request.readyState === XMLHttpRequest.DONE) {
                captureStatus.text = "Helper nicht erreichbar – lcd_engine_service.py starten"
            }
        }
        request.send()
    }

    function setCaptureState(enabled) {
        if (loadingCaptureState) return
        var request = new XMLHttpRequest()
        request.open("POST", "http://127.0.0.1:41722/config")
        request.setRequestHeader("Content-Type", "application/json")
        request.onreadystatechange = function() {
            if (request.readyState === XMLHttpRequest.DONE) {
                if (request.status === 200) readCaptureState()
                else captureStatus.text = "Speichern fehlgeschlagen – Helper prüfen"
            }
        }
        request.send(JSON.stringify({captureSignalRGB: enabled}))
    }

    Timer {
        interval: 1500
        running: true
        repeat: true
        onTriggered: readCaptureState()
    }

    Component.onCompleted: readCaptureState()

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        Pane {
            Layout.fillWidth: true
            background: Rectangle { color: "#111820"; radius: 8; border.color: "#263541" }
            ColumnLayout {
                anchors.fill: parent
                Label { text: "Independent LCD Engine"; font.pixelSize: 20; font.bold: true; color: "#E8F0F5" }
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: "#AAB9C4"
                    text: "This add-on discovers the local LCD Engine helper. The helper owns rendering and USB/HID frame transfer."
                }
                Label {
                    Layout.fillWidth: true
                    color: "#42D6C5"
                    text: "Use the switch below to keep sending the live SignalRGB canvas. The visual editor configures rotation, layout, backgrounds and widgets."
                }
                RowLayout {
                    Layout.fillWidth: true
                    CheckBox {
                        id: captureSwitch
                        text: "SignalRGB-Effekt erfassen (nicht verfügbar)"
                        enabled: false
                        onToggled: setCaptureState(checked)
                    }
                }
                Label {
                    id: captureStatus
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: "#AAB9C4"
                    text: "Prüfe lokalen Helper …"
                }
                Button {
                    text: "LCD Editor öffnen"
                    onClicked: Qt.openUrlExternally("http://127.0.0.1:41722/")
                }
            }
        }
    }
}
