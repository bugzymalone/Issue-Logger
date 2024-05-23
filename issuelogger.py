import sys
import os
from datetime import datetime
from io import BytesIO
import pyautogui
import pygetwindow as gw
from PIL import ImageGrab, Image
import sqlite3
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QLabel,
                             QLineEdit, QTextEdit, QListWidget, QHBoxLayout, QMessageBox, QFileDialog, QScrollArea, QTabWidget)
from PyQt5.QtGui import QIcon, QPixmap, QImage
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QMetaObject, QTimer, QBuffer, QThread, pyqtSlot
import keyboard
import mss

class ImageLoaderThread(QThread):
    images_loaded = pyqtSignal(list)

    def __init__(self, project_path, finding_id):
        super().__init__()
        self.project_path = project_path
        self.finding_id = finding_id

    def run(self):
        conn = sqlite3.connect(self.project_path)
        c = conn.cursor()
        c.execute('SELECT image FROM Images WHERE finding_id=?', (self.finding_id,))
        images = c.fetchall()
        conn.close()
        self.images_loaded.emit(images)

class SafeCaller(QObject):
    update_gui = pyqtSignal(str, str, bytes, bytes)  # title, description, full screen image, focused window image

class ScreenShotTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project_path = None
        self.project_id = None
        self.current_finding_id = None
        self.initUI()
        self.safe_caller = SafeCaller()
        self.safe_caller.update_gui.connect(self.handle_screenshot_data)
        self.image_loader_thread = None
        self.showMinimized()

    def initUI(self):
        self.setWindowTitle("Issue Logger")
        self.setWindowIcon(QIcon("path_to_your_icon.png"))
        self.resize(1000, 800)

        self.layout = QHBoxLayout()
        self.entry_list = QListWidget()
        self.entry_list.currentItemChanged.connect(self.display_entry)
        self.layout.addWidget(self.entry_list, 1)

        self.tab_widget = QTabWidget()

        self.main_tab = QWidget()
        self.additional_tab = QWidget()

        self.init_main_tab()
        self.init_additional_tab()

        self.tab_widget.addTab(self.main_tab, "Main View")
        self.tab_widget.addTab(self.additional_tab, "Additional Details")

        self.layout.addWidget(self.tab_widget, 3)

        container = QWidget()
        container.setLayout(self.layout)
        self.setCentralWidget(container)

        self.startup_dialog()

    def init_main_tab(self):
        main_layout = QVBoxLayout()
        self.title_input = QLineEdit()
        self.description_input = QTextEdit()

        self.image_area = QScrollArea()
        self.image_widget = QWidget()
        self.image_layout = QVBoxLayout()
        self.image_widget.setLayout(self.image_layout)
        self.image_area.setWidget(self.image_widget)
        self.image_area.setWidgetResizable(True)

        self.save_image_button = QPushButton('Save Images to Disk')
        self.save_image_button.clicked.connect(self.save_images_to_disk)

        self.copy_image_button = QPushButton('Copy Image Clipboard')
        self.copy_image_button.clicked.connect(self.copy_images_to_clipboard)

        self.save_finding_button_main = QPushButton('Save Finding')
        self.save_finding_button_main.clicked.connect(self.save_details)

        main_layout.addWidget(QLabel('Title:'))
        main_layout.addWidget(self.title_input)
        main_layout.addWidget(QLabel('Description:'))
        main_layout.addWidget(self.description_input)
        main_layout.addWidget(QLabel('Images:'))
        main_layout.addWidget(self.image_area)
        main_layout.addWidget(self.save_image_button)
        main_layout.addWidget(self.copy_image_button)
        main_layout.addWidget(self.save_finding_button_main)

        self.main_tab.setLayout(main_layout)

    def init_additional_tab(self):
        additional_layout = QVBoxLayout()
        self.finding_input = QTextEdit()
        self.gpt_prompt_input = QLineEdit()
        self.gpt_prompt_input.setText("Write a penetration report finding in UK English. Be descriptive. Use the following headers, Description, Risk (Description), Recommendation (Use bullet points if it is better), References (use only full URLs). The following issue relates to: ")

        self.copy_gpt_button = QPushButton('Copy')
        self.copy_gpt_button.clicked.connect(self.copy_gpt_prompt)

        self.save_finding_button_additional = QPushButton('Save Finding')
        self.save_finding_button_additional.clicked.connect(self.save_details)

        additional_layout.addWidget(QLabel('Finding:'))
        additional_layout.addWidget(self.finding_input)
        additional_layout.addWidget(QLabel('GPT Prompt:'))
        additional_layout.addWidget(self.gpt_prompt_input)
        additional_layout.addWidget(self.copy_gpt_button)
        additional_layout.addWidget(self.save_finding_button_additional)

        self.additional_tab.setLayout(additional_layout)

    def startup_dialog(self):
        response = QMessageBox.question(self, "Start Session", "Do you want to load an existing project?", QMessageBox.Yes | QMessageBox.No)
        if response == QMessageBox.Yes:
            self.load_project()
        else:
            self.new_project()

    def new_project(self):
        project_path, _ = QFileDialog.getSaveFileName(self, "Create New Project", "", "Issue Logger Database (*.ild)")
        if not project_path:
            QMessageBox.warning(self, "Error", "Project not created. Please try again.")
            return
        self.project_path = project_path
        print(f"Creating new project at {self.project_path}")
        self.init_database()
        print(f"New project path set: {self.project_path}, project ID set: {self.project_id}")
        self.showNormal()

    def load_project(self):
        project_path, _ = QFileDialog.getOpenFileName(self, "Load Project", "", "Issue Logger Database (*.ild)")
        if not project_path:
            QMessageBox.warning(self, "Error", "Project not loaded. Please try again.")
            return
        self.project_path = project_path
        print(f"Loading project from {self.project_path}")
        self.init_database()  # Ensure the database schema is updated
        self.load_database()
        print(f"Loaded project path set: {self.project_path}, project ID set: {self.project_id}")
        self.showNormal()

    def init_database(self):
        print(f"Initializing database at {self.project_path}...")
        conn = sqlite3.connect(self.project_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS Projects (
                project_id INTEGER PRIMARY KEY,
                project_name TEXT,
                creation_date TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS Findings (
                finding_id INTEGER PRIMARY KEY,
                project_id INTEGER,
                title TEXT,
                description TEXT,
                finding_text TEXT,
                FOREIGN KEY (project_id) REFERENCES Projects (project_id)
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS Images (
                image_id INTEGER PRIMARY KEY,
                finding_id INTEGER,
                image BLOB,
                FOREIGN KEY (finding_id) REFERENCES Findings (finding_id)
            )
        ''')
        conn.commit()
        # Insert a new project entry
        c.execute('''
            INSERT INTO Projects (project_name, creation_date)
            VALUES (?, ?)
        ''', ("New Project", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.project_id = c.lastrowid
        print(f"New project created with project_id: {self.project_id}")
        conn.commit()
        conn.close()

    def load_database(self):
        print(f"Loading database from {self.project_path}...")
        conn = sqlite3.connect(self.project_path)
        c = conn.cursor()
        c.execute('SELECT project_id FROM Projects LIMIT 1')
        self.project_id = c.fetchone()[0]
        print(f"Loaded project with project_id: {self.project_id}")
        c.execute('SELECT finding_id, title FROM Findings WHERE project_id=?', (self.project_id,))
        findings = c.fetchall()
        for finding_id, title in findings:
            self.entry_list.addItem(f"{title} - {finding_id}")
        conn.close()

    def handle_screenshot_data(self, title, description, full_screen_data, focused_window_data):
        print(f"Handling screenshot data... project_path: {self.project_path}, project_id: {self.project_id}")
        self.current_finding_id = None  # Reset current finding ID for new finding
        self.title_input.setText(title)
        self.description_input.setText(description)
        self.finding_input.clear()
        self.display_images([(full_screen_data,), (focused_window_data,)])
        QMetaObject.invokeMethod(self, 'showNormal', Qt.QueuedConnection)

    def copy_gpt_prompt(self):
        text = self.gpt_prompt_input.text()
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Copied", "GPT Prompt text has been copied to clipboard.")

    def take_screenshot(self):
        print(f"Taking screenshot... project_path: {self.project_path}, project_id: {self.project_id}")
        if not self.project_path or not self.project_id:
            print("Error: Project path or project ID is not set.")
            QMessageBox.warning(self, "Project Not Saved", "Please create or load a project first.")
            return

        self.showMinimized()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Full screen screenshot using ImageGrab to handle multiple monitors
        full_screenshot = ImageGrab.grab(all_screens=True)
        full_screenshot_data = BytesIO()
        full_screenshot.save(full_screenshot_data, format='PNG')
        full_screenshot_data = full_screenshot_data.getvalue()
        
        # Focused window screenshot using mss
        focused_window = gw.getActiveWindow()
        if focused_window and focused_window.visible:
            with mss.mss() as sct:
                monitor = {
                    "top": focused_window.top,
                    "left": focused_window.left,
                    "width": focused_window.width,
                    "height": focused_window.height,
                    "mon": 1
                }
                window_screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", window_screenshot.size, window_screenshot.rgb)
                focused_window_data = BytesIO()
                img.save(focused_window_data, format='PNG')
                focused_window_data = focused_window_data.getvalue()
        else:
            focused_window_data = None

        # Emit signal to update GUI
        self.safe_caller.update_gui.emit("", "", full_screenshot_data, focused_window_data)

    def display_entry(self, current, previous):
        if current:
            item_text = current.text()
            finding_id = item_text.split(" - ")[-1]
            self.current_finding_id = finding_id

            # Load basic details
            conn = sqlite3.connect(self.project_path)
            c = conn.cursor()
            c.execute('SELECT title, description, finding_text FROM Findings WHERE finding_id=?', (finding_id,))
            finding = c.fetchone()
            if finding:
                self.title_input.setText(finding[0])
                self.description_input.setText(finding[1])
                self.finding_input.setText(finding[2])
            conn.close()

            # Load images asynchronously
            if self.image_loader_thread:
                self.image_loader_thread.terminate()
            self.image_loader_thread = ImageLoaderThread(self.project_path, finding_id)
            self.image_loader_thread.images_loaded.connect(self.display_images)
            self.image_loader_thread.start()

    @pyqtSlot(list)
    def display_images(self, images):
        # Clear previous images
        for i in reversed(range(self.image_layout.count())):
            widget = self.image_layout.itemAt(i).widget()
            if widget is not None:
                widget.deleteLater()

        # Display new images
        for idx, image_data in enumerate(images):
            print(f"Displaying image {idx+1}/{len(images)}")
            image = Image.open(BytesIO(image_data[0]))
            image = image.convert("RGBA")  # Ensure the image is in a format compatible with QImage
            qimage = QImage(image.tobytes(), image.width, image.height, QImage.Format_RGBA8888)
            pixmap = QPixmap.fromImage(qimage)
            image_label = QLabel()
            image_label.setPixmap(pixmap)
            self.image_layout.addWidget(image_label)

    def save_images_to_disk(self):
        current_item = self.entry_list.currentItem()
        if current_item:
            finding_id = current_item.text().split(" - ")[-1]
            conn = sqlite3.connect(self.project_path)
            c = conn.cursor()
            c.execute('SELECT image FROM Images WHERE finding_id=?', (finding_id,))
            images = c.fetchall()
            for idx, image_data in enumerate(images):
                try:
                    image = Image.open(BytesIO(image_data[0]))
                    # Log the chosen save path
                    print(f"Opening file dialog to save image {idx+1}")
                    save_path, _ = QFileDialog.getSaveFileName(self, "Save Image", f"image_{finding_id}_{idx}.png", "PNG Files (*.png)")
                    print(f"Chosen save path: {save_path}")
                    if save_path:
                        # Save the image to the chosen location
                        image.save(save_path, "PNG")
                        print(f"Image {idx+1} saved to {save_path}")
                        QMessageBox.information(self, "Save Successful", f"Image {idx+1} saved to {save_path}")
                    else:
                        print(f"Saving of image {idx+1} was cancelled.")
                        QMessageBox.warning(self, "Save Cancelled", f"Saving of image {idx+1} was cancelled.")
                except Exception as e:
                    print(f"Failed to save image {idx+1}: {str(e)}")
                    QMessageBox.critical(self, "Save Error", f"Failed to save image {idx+1}: {str(e)}")
            conn.close()
        else:
            print("No selection made for saving images.")
            QMessageBox.warning(self, "No Selection", "Please select an entry from the list to save images.")

    def copy_images_to_clipboard(self):
        current_item = self.entry_list.currentItem()
        if current_item:
            finding_id = current_item.text().split(" - ")[-1]
            conn = sqlite3.connect(self.project_path)
            c = conn.cursor()
            c.execute('SELECT image FROM Images WHERE finding_id=?', (finding_id,))
            images = c.fetchall()
            if images:
                clipboard = QApplication.clipboard()
                for image_data in images:
                    image = Image.open(BytesIO(image_data[0]))
                    image = image.convert("RGBA")
                    qimage = QImage(image.tobytes(), image.width, image.height, QImage.Format_RGBA8888)
                    pixmap = QPixmap.fromImage(qimage)
                    clipboard.setPixmap(pixmap)
            conn.close()

    def save_finding(self):
        title = self.title_input.text().strip()
        description = self.description_input.toPlainText().strip()
        finding_text = self.finding_input.toPlainText().strip()

        if not title:
            QMessageBox.warning(self, "Error", "Title cannot be empty.")
            return

        conn = sqlite3.connect(self.project_path)
        c = conn.cursor()

        if self.current_finding_id:
            # Update existing finding
            c.execute('''
                UPDATE Findings
                SET title=?, description=?, finding_text=?
                WHERE finding_id=?
            ''', (title, description, finding_text, self.current_finding_id))
            finding_id = self.current_finding_id
        else:
            # Insert new finding
            c.execute('''
                INSERT INTO Findings (project_id, title, description, finding_text)
                VALUES (?, ?, ?, ?)
            ''', (self.project_id, title, description, finding_text))
            finding_id = c.lastrowid
            self.entry_list.addItem(f"{title} - {finding_id}")

        # Save images associated with this finding
        c.execute('DELETE FROM Images WHERE finding_id=?', (finding_id,))
        image_widgets = [self.image_layout.itemAt(i).widget() for i in range(self.image_layout.count())]
        for image_widget in image_widgets:
            pixmap = image_widget.pixmap()
            if pixmap:
                buffer = QBuffer()
                buffer.open(QBuffer.ReadWrite)
                qimage = pixmap.toImage()
                qimage.save(buffer, "PNG")
                image_data = buffer.data()
                c.execute('''
                    INSERT INTO Images (finding_id, image)
                    VALUES (?, ?)
                ''', (finding_id, image_data))

        conn.commit()
        conn.close()

        QMessageBox.information(self, "Save Successful", "Issue Saved.")

    def save_details(self):
        print(f"Saving details... project_path: {self.project_path}, project_id: {self.project_id}")
        self.save_finding()

def setup_hotkey(app):
    keyboard.add_hotkey('ctrl+alt+p', lambda: QTimer.singleShot(0, app.take_screenshot))

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ScreenShotTool()
    setup_hotkey(window)
    sys.exit(app.exec_())
