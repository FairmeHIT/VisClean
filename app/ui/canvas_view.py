from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QRubberBand


class CanvasView(QGraphicsView):
    selectionMade = Signal(QRectF)
    selectionCleared = Signal()
    moveMade = Signal(QRectF, QRectF)
    copyRequested = Signal()
    pasteRequested = Signal()
    textRequested = Signal(QPointF)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(self.renderHints())
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._selection_items: list[QGraphicsRectItem] = []
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self._origin = QPoint()
        self._selecting = False
        self._panning = False
        self._pan_origin = QPoint()
        self._mode = "pan"
        self._zoom = 0
        self._move_active = False
        self._move_item: QGraphicsRectItem | None = None
        self._move_source_rect = QRectF()
        self._move_scene_origin = QPointF()
        self._move_delta = QPointF()
        self._move_button = Qt.MouseButton.LeftButton
        self._text_pending_origin = QPointF()
        self.viewport().installEventFilter(self)

    def set_image(self, image_path: str, *, preserve_view: bool = False) -> None:
        pixmap = QPixmap(image_path)
        self.scene().clear()
        self._pixmap_item = self.scene().addPixmap(pixmap)
        self._selection_items = []
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        if not preserve_view:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = 0

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.RightButton:
                    return self._start_pan_or_move(event)
                if self._mode == "text":
                    return self._place_text(event)
                if self._mode == "select":
                    return self._start_selection(event)
                if self._mode == "move":
                    return self._start_move(event)
            if event.type() == QEvent.Type.MouseMove:
                if self._panning:
                    return self._update_pan(event)
                if self._move_active:
                    return self._update_move(event)
                return self._update_selection(event)
            if event.type() == QEvent.Type.MouseButtonRelease:
                if self._move_active and event.button() == self._move_button:
                    return self._finish_move(event)
                if event.button() == Qt.MouseButton.RightButton:
                    return self._finish_pan(event)
                return self._finish_selection(event)
        return super().eventFilter(watched, event)

    def _event_pos(self, event) -> QPoint:
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _place_text(self, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton or self._pixmap_item is None:
            return False
        scene_pos = self.mapToScene(self._event_pos(event))
        self._text_pending_origin = scene_pos
        self.set_select_mode()
        self.textRequested.emit(scene_pos)
        return True

    def _start_selection(self, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton or self._pixmap_item is None:
            return False
        if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) and self._selection_items:
            self.clear_selection()
            self.selectionCleared.emit()
        self._origin = self._event_pos(event)
        self._rubber_band.setGeometry(QRect(self._origin, self._origin))
        self._rubber_band.show()
        self._selecting = True
        return True

    def _update_selection(self, event) -> bool:
        if not self._selecting or self._panning:
            return False
        rect = QRect(self._origin, self._event_pos(event)).normalized()
        self._rubber_band.setGeometry(rect)
        return True

    def _finish_selection(self, event) -> bool:
        if not self._selecting or event.button() != Qt.MouseButton.LeftButton:
            return False
        self._rubber_band.hide()
        view_rect = self._rubber_band.geometry().normalized()
        scene_rect = self.mapToScene(view_rect).boundingRect()
        image_rect = self.sceneRect()
        scene_rect = scene_rect.intersected(image_rect)
        self._selecting = False
        if scene_rect.isValid() and scene_rect.width() > 1 and scene_rect.height() > 1:
            self.set_selection_rect(scene_rect)
            self.selectionMade.emit(scene_rect)
        return True

    def _start_move(self, event) -> bool:
        if self._pixmap_item is None:
            return False
        scene_pos = self.mapToScene(self._event_pos(event))
        item = self._selection_item_at(scene_pos) if self._selection_items else None
        if item is None:
            self.clear_selection()
            self.selectionCleared.emit()
            return True
        self._move_item = item
        self._move_source_rect = QRectF(item.rect())
        self._move_scene_origin = scene_pos
        self._move_delta = QPointF()
        self._move_button = event.button()
        self._move_active = True
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        return True

    def _selection_item_at(self, scene_pos) -> QGraphicsRectItem | None:
        for item in reversed(self._selection_items):
            if item.rect().contains(scene_pos):
                return item
        return None

    def _update_move(self, event) -> bool:
        scene_pos = self.mapToScene(self._event_pos(event))
        self._move_delta = scene_pos - self._move_scene_origin
        if self._move_item is not None:
            self._move_item.setRect(self._move_source_rect.translated(self._move_delta))
        return True

    def _finish_move(self, event) -> bool:
        if not self._move_active or event.button() != self._move_button:
            return False
        self._move_active = False
        if self._mode == "move":
            self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        source_rect = self._move_source_rect
        if self._move_item is not None:
            self._move_item.setRect(source_rect)
        self._move_item = None
        if self._move_delta.isNull():
            self.clear_selection()
            self.selectionCleared.emit()
            return True
        target_rect = QRectF(source_rect).translated(self._move_delta)
        self.moveMade.emit(source_rect, target_rect)
        return True

    def _start_pan_or_move(self, event) -> bool:
        if self._pixmap_item is None:
            return False
        scene_pos = self.mapToScene(self._event_pos(event))
        if self._selection_items and self._selection_item_at(scene_pos) is not None:
            return self._start_move(event)
        return self._start_pan(event)

    def _start_pan(self, event) -> bool:
        if self._pixmap_item is None:
            return False
        self._panning = True
        self._pan_origin = self._event_pos(event)
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        return True

    def _update_pan(self, event) -> bool:
        current = self._event_pos(event)
        delta = current - self._pan_origin
        self._pan_origin = current
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
        return True

    def _finish_pan(self, event) -> bool:
        if not self._panning:
            return False
        self._panning = False
        if self._mode == "select":
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        return True

    def set_selection_rect(self, rect: QRectF) -> None:
        pen = QPen(QColor(230, 57, 70), 3)
        brush = QBrush(QColor(230, 57, 70, 70))
        selection_item = self.scene().addRect(rect, pen, brush)
        selection_item.setZValue(10)
        self._selection_items.append(selection_item)
        self.ensureVisible(rect, 32, 32)

    def set_selection_rects(self, rects: list[QRectF]) -> None:
        self.clear_selection()
        for rect in rects:
            self.set_selection_rect(rect)

    def clear_selection(self) -> None:
        for item in self._selection_items:
            self.scene().removeItem(item)
        self._selection_items = []

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.dragMode() == QGraphicsView.DragMode.NoDrag:
            self._origin = self._event_pos(event)
            self._rubber_band.setGeometry(QRect(self._origin, self._origin))
            self._rubber_band.show()
            self._selecting = True
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._selecting:
            rect = QRect(self._origin, self._event_pos(event)).normalized()
            self._rubber_band.setGeometry(rect)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._selecting and event.button() == Qt.MouseButton.LeftButton:
            self._rubber_band.hide()
            view_rect = self._rubber_band.geometry()
            scene_rect = self.mapToScene(view_rect).boundingRect()
            self._selecting = False
            if scene_rect.isValid() and scene_rect.width() > 1 and scene_rect.height() > 1:
                self.set_selection_rect(scene_rect)
                self.selectionMade.emit(scene_rect)
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self._zoom += 1 if factor > 1 else -1
            self.scale(factor, factor)
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        modifiers = event.modifiers()
        key = event.key()
        if modifiers & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_C:
            self.copyRequested.emit()
            event.accept()
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_V:
            self.pasteRequested.emit()
            event.accept()
            return
        if self._mode == "move" and self._selection_items and not self._move_active:
            dx = dy = 0
            key = event.key()
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
                step = 50 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 10
                dx = -step if key == Qt.Key.Key_Left else step if key == Qt.Key.Key_Right else 0
                dy = -step if key == Qt.Key.Key_Up else step if key == Qt.Key.Key_Down else 0
                source = QRectF(self._selection_items[-1].rect())
                target = QRectF(source).translated(dx, dy)
                self.moveMade.emit(source, target)
                event.accept()
                return
        super().keyPressEvent(event)

    def set_pan_mode(self) -> None:
        self._mode = "pan"
        self._selecting = False
        self._panning = False
        self._move_active = False
        self._rubber_band.hide()
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)

    def set_select_mode(self) -> None:
        self._mode = "select"
        self._selecting = False
        self._panning = False
        self._move_active = False
        self._rubber_band.hide()
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    def set_move_mode(self) -> None:
        self._mode = "move"
        self._selecting = False
        self._panning = False
        self._move_active = False
        self._rubber_band.hide()
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
        self.setFocus()

    def set_text_mode(self) -> None:
        self._mode = "text"
        self._selecting = False
        self._panning = False
        self._move_active = False
        self._rubber_band.hide()
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self.setFocus()
