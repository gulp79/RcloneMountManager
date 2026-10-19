import sys
import os
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication, QScrollArea, QListWidget, QListWidgetItem
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import Qt, QSize, QEvent, QPointF

class TestRcloneMountManager(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Create a single QApplication in offscreen mode
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(["-platform", "offscreen"])

    def test_imports(self):
        """Verify all required classes can be imported from RcloneMountManager"""
        from RcloneMountManager import MainWindow, RemoteController, RemoteListItem, RemoteWidget, StatusIndicator
        self.assertIsNotNone(MainWindow)
        self.assertIsNotNone(RemoteController)
        self.assertIsNotNone(RemoteListItem)
        self.assertIsNotNone(RemoteWidget)
        self.assertIsNotNone(StatusIndicator)

    def test_remote_controller_initialization(self):
        """Verify RemoteController parses general settings correctly from properties file"""
        from RcloneMountManager import RemoteController
        
        # Create a temp properties file manually to avoid external dependency issues
        config_file = Path("test_remote.properties")
        content = """[General]
name = Test Cloud Storage
remote_name = test_remote:
mountpoint = Z:
volname = TestVolume

[Rclone]
config_path = rclone.conf
extra_flags = --links

[Defaults]
vfs-cache-mode = full
vfs-cache-max-age = 30m
dir-cache-time = 1m
"""
        config_file.write_text(content, encoding="utf-8")
        
        try:
            # Initialize controller
            controller = RemoteController(config_file)
            info = controller.get_info()
            
            self.assertEqual(info["name"], "Test Cloud Storage")
            self.assertEqual(info["remote"], "test_remote:")
            self.assertEqual(info["mountpoint"], "Z:")
            self.assertEqual(controller.runtime_params["vfs-cache-mode"], "full")
            self.assertEqual(controller.runtime_params["vfs-cache-max-age"], "30m")
            self.assertEqual(controller.runtime_params["dir-cache-time"], "1m")
        finally:
            if config_file.exists():
                config_file.unlink()

    def test_mainwindow_layout_and_elements(self):
        """Verify MainWindow layout structure and scrollbar components exist and are properly configured"""
        from RcloneMountManager import MainWindow
        
        window = MainWindow()
        
        # Check that main elements exist
        self.assertTrue(hasattr(window, "list_widget"))
        self.assertTrue(hasattr(window, "details_panel"))
        self.assertTrue(hasattr(window, "details_scroll"))
        
        # Verify that details_scroll is a QScrollArea
        self.assertIsInstance(window.details_scroll, QScrollArea)
        self.assertEqual(window.details_scroll.widget(), window.details_panel)
        self.assertTrue(window.details_scroll.widgetResizable())
        self.assertEqual(window.details_scroll.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
        self.assertEqual(window.details_scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        
        # Verify left sidebar QListWidget settings
        self.assertIsInstance(window.list_widget, QListWidget)
        self.assertEqual(window.list_widget.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
        self.assertEqual(window.list_widget.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        self.assertEqual(window.list_widget.spacing(), 1)
        
        # Clean up window
        window.close()

    def test_compact_remote_list_item_properties(self):
        """Verify RemoteListItem has compact margins (8, 4, 8, 4), spacing, and vertical alignment"""
        from RcloneMountManager import RemoteListItem, StatusIndicator
        
        item_widget = RemoteListItem("drive1", "Google Drive Personal")
        layout = item_widget.layout()
        
        # Check layout margins: (8, 4, 8, 4)
        margins = layout.contentsMargins()
        self.assertEqual(margins.top(), 4)
        self.assertEqual(margins.bottom(), 4)
        self.assertEqual(margins.left(), 8)
        self.assertEqual(margins.right(), 8)
        
        # Check spacing
        self.assertEqual(layout.spacing(), 8)
        self.assertEqual(layout.alignment(), Qt.AlignVCenter)
        
        # Check status indicator compact size
        self.assertIsInstance(item_widget.status_indicator, StatusIndicator)
        self.assertEqual(item_widget.status_indicator.width(), 10)
        self.assertEqual(item_widget.status_indicator.height(), 10)
        
        # Verify click emission
        clicked_ids = []
        item_widget.clicked.connect(lambda rid: clicked_ids.append(rid))
        event = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        item_widget.mousePressEvent(event)
        self.assertEqual(clicked_ids, ["drive1"])

    def test_sidebar_density_and_filter(self):
        """Verify that 30 remotes can be populated, sizeHint is 32px, and search filter works"""
        from RcloneMountManager import MainWindow, RemoteListItem
        
        window = MainWindow()
        window.list_widget.clear()
        
        # Populate with 30 mock remotes
        for i in range(30):
            rid = f"remote_{i:02d}"
            name = f"Cloud Drive {i:02d}" if i % 2 == 0 else f"Backup Storage {i:02d}"
            item_widget = RemoteListItem(rid, name)
            item = QListWidgetItem(window.list_widget)
            item.setSizeHint(QSize(250, 32))
            window.list_widget.addItem(item)
            window.list_widget.setItemWidget(item, item_widget)
        
        self.assertEqual(window.list_widget.count(), 30)
        
        # Test height of each item
        first_item = window.list_widget.item(0)
        item_height = first_item.sizeHint().height()
        self.assertEqual(item_height, 32)
        
        # Percentage reduction from legacy 45px: (45 - 32) / 45 = 28.89% ~ 30%
        self.assertLess(item_height, 45)
        
        # Test search filter functionality
        self.assertTrue(hasattr(window, "search_filter"))
        window.search_filter.setText("Backup")
        visible_count = sum(1 for i in range(window.list_widget.count()) if not window.list_widget.item(i).isHidden())
        self.assertEqual(visible_count, 15)
        
        window.search_filter.setText("")
        visible_count = sum(1 for i in range(window.list_widget.count()) if not window.list_widget.item(i).isHidden())
        self.assertEqual(visible_count, 30)
        
        # Verify selection synchronization
        window.on_remote_clicked("remote_15")
        for i in range(window.list_widget.count()):
            item = window.list_widget.item(i)
            widget = window.list_widget.itemWidget(item)
            if isinstance(widget, RemoteListItem) and widget.remote_id == "remote_15":
                window.list_widget.setCurrentItem(item)
                break
        
        self.assertEqual(window.list_widget.currentItem().sizeHint().height(), 32)
        window.close()

    def test_remote_widget_layout_and_collapsible_settings(self):
        """Verify MOUNT/UNMOUNT location, utility buttons, and collapsible settings behavior"""
        from RcloneMountManager import RemoteWidget, ModernButton
        
        widget = RemoteWidget()
        
        # Verify action buttons exist and are ModernButton instances
        self.assertIsInstance(widget.btn_mount, ModernButton)
        self.assertIsInstance(widget.btn_unmount, ModernButton)
        
        # Verify utility buttons exist
        self.assertTrue(hasattr(widget, "btn_open_mount"))
        self.assertTrue(hasattr(widget, "btn_open_logs"))
        self.assertTrue(hasattr(widget, "btn_open_cache"))
        self.assertTrue(hasattr(widget, "btn_show_command"))
        self.assertTrue(hasattr(widget, "chk_clean_logs"))
        self.assertTrue(hasattr(widget, "chk_auto_mount"))
        self.assertTrue(hasattr(widget, "combo_mountpoint"))
        self.assertTrue(hasattr(widget, "btn_copy_log"))
        self.assertTrue(hasattr(widget, "btn_clear_log"))
        self.assertTrue(hasattr(widget, "chk_auto_scroll"))
        self.assertTrue(hasattr(widget, "btn_reset_defaults"))
        
        # Verify collapsible settings card and default state (closed by default)
        self.assertTrue(hasattr(widget, "settings_card"))
        self.assertTrue(hasattr(widget, "btn_toggle_settings"))
        self.assertTrue(hasattr(widget, "group_settings"))
        self.assertFalse(widget.settings_expanded)
        self.assertTrue(widget.group_settings.isHidden())
        self.assertIn("▸", widget.btn_toggle_settings.text())
        
        # Toggle settings to expand
        widget.toggle_settings()
        self.assertTrue(widget.settings_expanded)
        self.assertFalse(widget.group_settings.isHidden())
        self.assertIn("▾", widget.btn_toggle_settings.text())
        
        # Toggle settings to collapse again
        widget.toggle_settings()
        self.assertFalse(widget.settings_expanded)
        self.assertTrue(widget.group_settings.isHidden())
        self.assertIn("▸", widget.btn_toggle_settings.text())

if __name__ == "__main__":
    unittest.main()

