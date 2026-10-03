import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    anchors.fill: parent
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
                    text: "Select the LCD under Third Party Services, then customize its view, clock, CPU/RAM widgets, colors, brightness and frame rate in the service settings."
                }
            }
        }
    }
}
