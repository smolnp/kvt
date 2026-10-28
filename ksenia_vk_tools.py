import sys
import time
import vk_api
from vk_api.exceptions import ApiError
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QTextEdit, QSpinBox, QCheckBox, QMessageBox)
from PyQt6.QtCore import QThread, pyqtSignal


class KseniaCleanerWorker(QThread):
    """Поток очистки участников сообщества для Ksenia VK Tools."""
    progress = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, token, group_id, limit, delay, test_mode):
        super().__init__()
        self.token = token
        self.group_id = group_id
        self.limit = limit
        self.delay = delay
        self.test_mode = test_mode
        self._is_running = True

    def run(self):
        try:
            vk_session = vk_api.VkApi(token=self.token)
            vk = vk_session.get_api()

            self.progress.emit("Получение списка участников...")
            participants = []
            offset = 0
            while True:
                if not self._is_running:
                    break
                try:
                    response = vk.groups.getMembers(
                        group_id=self.group_id,
                        offset=offset,
                        count=1000,
                        fields='deactivated'
                    )
                except ApiError as e:
                    self.error.emit(f"Ошибка получения участников: {e}")
                    return
                items = response.get('items', [])
                if not items:
                    break
                participants.extend(items)
                offset += 1000
                if offset >= response.get('count', 0):
                    break

            self.progress.emit(f"Получено {len(participants)} участников.")

            # Исключаем администраторов и владельца токена
            manager_ids = set()
            try:
                managers_resp = vk.groups.getMembers(
                    group_id=self.group_id,
                    filter='managers',
                    count=1000
                )
                for item in managers_resp.get('items', []):
                    if isinstance(item, dict):
                        manager_ids.add(item['id'])
                    else:
                        manager_ids.add(item)
            except ApiError:
                pass

            removed_count = 0
            for participant in participants:
                if not self._is_running:
                    break
                if removed_count >= self.limit:
                    self.progress.emit(f"Достигнут лимит {self.limit}, остановка.")
                    break

                user_id = participant['id'] if isinstance(participant, dict) else participant

                if user_id in manager_ids:
                    self.progress.emit(f"Пропуск администратора: {user_id}")
                    continue

                if self.test_mode:
                    self.progress.emit(f"[ТЕСТ] Будет удалён: {user_id}")
                else:
                    try:
                        vk.groups.removeUser(group_id=self.group_id, user_id=user_id)
                        self.progress.emit(f"Удалён: {user_id}")
                    except ApiError as e:
                        self.progress.emit(f"Ошибка удаления {user_id}: {e}")
                        if e.code == 15:
                            self.error.emit("Доступ запрещён (code 15). Проверьте права токена.")
                            return
                        if e.code == 29:
                            self.error.emit("Достигнут лимит запросов (code 29). Остановка.")
                            return

                removed_count += 1
                time.sleep(self.delay)

            self.progress.emit(f"Обработка завершена. Удалено: {removed_count}.")
            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self._is_running = False


class KseniaVKToolsWindow(QMainWindow):
    """Главное окно приложения Ksenia VK Tools."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ksenia VK Tools")
        self.setGeometry(100, 100, 640, 580)
        self.worker = None

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Заголовок и подзаголовок
        app_title = QLabel("Ksenia VK Tools")
        app_title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 2px;")
        layout.addWidget(app_title)

        app_subtitle = QLabel("Менеджер сообщества — очистка участников")
        app_subtitle.setStyleSheet("color: gray; margin-bottom: 10px;")
        layout.addWidget(app_subtitle)

        # Форма ввода
        form_layout = QVBoxLayout()

        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Введите токен администратора (access_token)")
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        form_layout.addWidget(QLabel("Токен:"))
        form_layout.addWidget(self.token_input)

        self.group_input = QLineEdit()
        self.group_input.setPlaceholderText("ID сообщества (например, 123456789)")
        form_layout.addWidget(QLabel("ID сообщества:"))
        form_layout.addWidget(self.group_input)

        # Настройки
        settings_layout = QHBoxLayout()

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 1000)
        self.limit_spin.setValue(50)
        settings_layout.addWidget(QLabel("Лимит за запуск:"))
        settings_layout.addWidget(self.limit_spin)

        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(100, 5000)
        self.delay_spin.setValue(200)
        self.delay_spin.setSuffix(" мс")
        settings_layout.addWidget(QLabel("Задержка:"))
        settings_layout.addWidget(self.delay_spin)

        form_layout.addLayout(settings_layout)

        self.test_mode_check = QCheckBox("Тестовый режим (не удалять, только показать)")
        self.test_mode_check.setChecked(True)
        form_layout.addWidget(self.test_mode_check)

        layout.addLayout(form_layout)

        # Кнопки
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("Запустить")
        self.start_btn.clicked.connect(self.start_process)
        self.stop_btn = QPushButton("Остановить")
        self.stop_btn.clicked.connect(self.stop_process)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        layout.addLayout(button_layout)

        # Лог
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(QLabel("Лог:"))
        layout.addWidget(self.log_output)

    def log(self, message):
        self.log_output.append(message)

    def start_process(self):
        token = self.token_input.text().strip()
        group_id = self.group_input.text().strip()

        if not token or not group_id:
            QMessageBox.warning(self, "Ошибка", "Заполните токен и ID сообщества.")
            return

        if not group_id.lstrip('-').isdigit():
            QMessageBox.warning(self, "Ошибка", "ID сообщества должен быть числом.")
            return

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_output.clear()
        self.log("--- Запуск ---")

        self.worker = KseniaCleanerWorker(
            token=token,
            group_id=group_id,
            limit=self.limit_spin.value(),
            delay=self.delay_spin.value() / 1000.0,
            test_mode=self.test_mode_check.isChecked()
        )
        self.worker.progress.connect(self.log)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def stop_process(self):
        if self.worker:
            self.worker.stop()
            self.log("Остановка по запросу пользователя...")

    def on_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.log("--- Завершено ---")

    def on_error(self, error_msg):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.log(f"ОШИБКА: {error_msg}")
        QMessageBox.critical(self, "Ошибка", error_msg)


def main():
    app = QApplication(sys.argv)
    window = KseniaVKToolsWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
