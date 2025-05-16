# -*- coding: utf-8 -*-
# SPDX-License-Identifier: LGPL-2.1-or-later
# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2022 FreeCAD Project Association                        *
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

import Draft
import FreeCAD
import FreeCADGui
import Part
import Path
import Path.Op.Base as OpBase
import PathScripts.PathUtils as PathUtils

from PySide.QtCore import QT_TRANSLATE_NOOP

__title__ = "CAM Path Compound with Tool Controller"
__author__ = ""
__url__ = ""
__doc__ = ""


if False:
    Path.Log.setLevel(Path.Log.Level.DEBUG, Path.Log.thisModule())
    Path.Log.trackModule(Path.Log.thisModule())
else:
    Path.Log.setLevel(Path.Log.Level.INFO, Path.Log.thisModule())


translate = FreeCAD.Qt.translate


# Add base set of operation properties
def _addBaseProperties(compObj):
    compObj.addProperty(
        "App::PropertyBool",
        "Active",
        "Path",
        QT_TRANSLATE_NOOP("App::Property", "Make False, to prevent operation from generating code"),
    )
    compObj.addProperty(
        "App::PropertyString",
        "Comment",
        "Path",
        QT_TRANSLATE_NOOP("App::Property", "An optional comment for this Operation"),
    )
    compObj.addProperty(
        "App::PropertyString",
        "UserLabel",
        "Path",
        QT_TRANSLATE_NOOP("App::Property", "User Assigned Label"),
    )
    compObj.Active = True


# Add ToolController required properties
def _addToolController(compObj, groupObjs):
    compObj.addProperty(
        "App::PropertyLink",
        "ToolController",
        "Path",
        QT_TRANSLATE_NOOP(
            "App::Property",
            "The tool controller that will be used to calculate the path",
        ),
    )

    tcs = [groupObj.ToolController for groupObj in groupObjs]
    if tcs != [None] and len(set(tcs)) == 1:
        compObj.ToolController = tcs[0]
    else:
        compObj.ToolController = PathUtils.findToolController(compObj, None)
    if not compObj.ToolController:
        raise OpBase.PathNoTCException()


# Get list of tool controllers
def _getToolControllers(obj, proxy=None):
    try:
        job = PathUtils.findParentJob(obj)
    except Exception:
        job = None

    if job:
        return [tc for tc in job.Tools.Group]
    else:
        return []


class commandPathCompoundTC:
    def GetResources(self):
        return {
            "Pixmap": "CAM_CompoundTC",
            "MenuText": QT_TRANSLATE_NOOP("CAM_PathCompoundTC", "Path Compound TC"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "CAM_PathCompoundTC", "Creates compound of paths with tool controller"
            ),
        }

    def IsActive(self):
        if FreeCAD.ActiveDocument is not None:
            for o in FreeCAD.ActiveDocument.Objects:
                if o.Name[:3] == "Job":
                    return True
        return False

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        compoundObj = doc.addObject("Path::FeatureCompound", "PathCompound")

        selection = FreeCADGui.Selection.getSelection()
        groupObjs = [obj for obj in selection if isinstance(obj.Proxy, Path.Op.Base.ObjectOp)]
        compoundObj.Group = groupObjs

        PathUtils.getToolControllers = _getToolControllers
        PathUtils.addToJob(compoundObj)
        _addBaseProperties(compoundObj)
        _addToolController(compoundObj, groupObjs)
        doc.recompute()


if FreeCAD.GuiUp:
    # register the FreeCAD command
    FreeCADGui.addCommand("CAM_PathCompoundTC", commandPathCompoundTC())
