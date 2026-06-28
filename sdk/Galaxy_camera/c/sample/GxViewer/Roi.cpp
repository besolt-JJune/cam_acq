//--------------------------------------------------------------------------------
/**
\file     Roi.cpp
\brief    CRoi Class implementation file

\version  v1.0.1807.9271
\date     2018-07-27

<p>Copyright (c) 2017-2018</p>
*/
//----------------------------------------------------------------------------------
#include "Roi.h"
#include "ui_Roi.h"

//----------------------------------------------------------------------------------
/**
\Constructor of CRoi
\param[in]
\param[out]
\return void
*/
//----------------------------------------------------------------------------------
CRoi::CRoi(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::CRoi),
    m_hDevice(NULL),
    m_i64WidthInc(0),
    m_i64HeightInc(0),
    m_i64OffsetXInc(0),
    m_i64OffsetYInc(0)
{
    ui->setupUi(this);

    QFont font = this->font();
    font.setPointSize(10);
    this->setFont(font);

    //This property holds the way the widget accepts keyboard focus.
    //Avoid other focus policy which will exit this dialog by every time pressing "Enter"
    ui->ROISettingClose->setFocusPolicy(Qt::NoFocus);

    // Close when Mainwindow is closed
    this->setAttribute(Qt::WA_QuitOnClose, false);

    // Set all spinbox do not emit the valueChanged() signal while typing.
    QObjectList pobjGroupList = this->children();
        foreach (QObject *pobjGroup, pobjGroupList)
        {
            QObjectList pobjItemList = pobjGroup->children();
            QAbstractSpinBox *pobjSpinbox;
            foreach (QObject *pobjItem, pobjItemList)
            {
                pobjSpinbox = qobject_cast<QAbstractSpinBox*>(pobjItem);
                if (pobjSpinbox)
                {
                    pobjSpinbox->setKeyboardTracking(false);
                }
            }
        }
}

//----------------------------------------------------------------------------------
/**
\Destructor of CRoi
\param[in]
\param[out]
\return void
*/
//----------------------------------------------------------------------------------
CRoi::~CRoi()
{
    delete ui;
}

//----------------------------------------------------------------------------------
/**
\ Close this dialog
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::on_ROISettingClose_clicked()
{
    this->close();

    return;
}

//----------------------------------------------------------------------------------
/**
\ Enable all UI Groups
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::EnableUI()
{
    // Release item signals
    QObjectList pobjGroupList = this->children();
        foreach (QObject *pobjGroup, pobjGroupList)
        {
            QObjectList pobjItemList = pobjGroup->children();
            foreach (QObject *pobjItem, pobjItemList)
            {
                pobjItem->blockSignals(false);
            }
        }

    ui->ROISettings->setEnabled(true);

    return;
}

//----------------------------------------------------------------------------------
/**
\ Disable all UI Groups
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::DisableUI()
{
    // Block item signals
    QObjectList pobjGroupList = this->children();
        foreach (QObject *pobjGroup, pobjGroupList)
        {
            QObjectList pobjItemList = pobjGroup->children();
            foreach (QObject *pobjItem, pobjItemList)
            {
                pobjItem->blockSignals(true);
            }
        }

    ui->ROISettings->setEnabled(false);

    return;
}

//----------------------------------------------------------------------------------
/**
\ Update ROI UI Item range
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::ROIRangeUpdate()
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    GX_INT_VALUE stIntValue;

    // Get the range of image width (nMax is Maximum, nMin is Minimum, nInc is Step)
    emStatus = GXGetIntValue(m_hDevice, "Width", &stIntValue);
    GX_VERIFY(emStatus);

    m_i64WidthInc = stIntValue.nInc;

    ui->WidthSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->WidthSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->WidthSlider->setSingleStep(stIntValue.nInc);
    ui->WidthSlider->setPageStep(0);
    ui->WidthSpin->setSingleStep(stIntValue.nInc);
    ui->WidthSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                              .arg(stIntValue.nMin)
                              .arg(stIntValue.nMax)
                              .arg(stIntValue.nInc));
    ui->WidthSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                .arg(stIntValue.nMin)
                                .arg(stIntValue.nMax)
                                .arg(stIntValue.nInc));

    // Get the range of image height (nMax is Maximum, nMin is Minimum, nInc is Step)
    emStatus = GXGetIntValue(m_hDevice, "Height", &stIntValue);
    GX_VERIFY(emStatus);

    m_i64HeightInc = stIntValue.nInc;

    ui->HeightSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->HeightSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->HeightSlider->setSingleStep(stIntValue.nInc);
    ui->HeightSlider->setPageStep(0);
    ui->HeightSpin->setSingleStep(stIntValue.nInc);
    ui->HeightSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                               .arg(stIntValue.nMin)
                               .arg(stIntValue.nMax)
                               .arg(stIntValue.nInc));
    ui->HeightSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                 .arg(stIntValue.nMin)
                                 .arg(stIntValue.nMax)
                                 .arg(stIntValue.nInc));

    // Get the range of image offsetx (nMax is Maximum, nMin is Minimum, nInc is Step)
    emStatus = GXGetIntValue(m_hDevice, "OffsetX", &stIntValue);
    GX_VERIFY(emStatus);

    m_i64OffsetXInc = stIntValue.nInc;

    ui->OffsetXSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->OffsetXSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->OffsetXSlider->setSingleStep(stIntValue.nInc);
    ui->OffsetXSlider->setPageStep(0);
    ui->OffsetXSpin->setSingleStep(stIntValue.nInc);
    ui->OffsetXSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                .arg(stIntValue.nMin)
                                .arg(stIntValue.nMax)
                                .arg(stIntValue.nInc));
    ui->OffsetXSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                  .arg(stIntValue.nMin)
                                  .arg(stIntValue.nMax)
                                  .arg(stIntValue.nInc));

    // Get the range of image offsety (nMax is Maximum, nMin is Minimum, nInc is Step)
    emStatus = GXGetIntValue(m_hDevice, "OffsetY", &stIntValue);
    GX_VERIFY(emStatus);

    m_i64OffsetYInc = stIntValue.nInc;

    ui->OffsetYSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->OffsetYSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->OffsetYSlider->setSingleStep(stIntValue.nInc);
    ui->OffsetYSlider->setPageStep(0);
    ui->OffsetYSpin->setSingleStep(stIntValue.nInc);
    ui->OffsetYSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                .arg(stIntValue.nMin)
                                .arg(stIntValue.nMax)
                                .arg(stIntValue.nInc));
    ui->OffsetYSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                  .arg(stIntValue.nMin)
                                  .arg(stIntValue.nMax)
                                  .arg(stIntValue.nInc));

    return;
}

//----------------------------------------------------------------------------------
/**
\ Get device handle from mainwindow, and get param for this dialog
\param[in]      hDeviceHandle   Device handle
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::GetDialogInitParam(GX_DEV_HANDLE hDeviceHandle)
{
    // Device handle transfered and storaged
    m_hDevice = hDeviceHandle;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;

    // Disable all UI items and block signals
    DisableUI();

    /// ******************************************************************************************** ///
    /// Width, Height, OffsetX, OffsetY part
    /// ******************************************************************************************** ///
    // Get image width
    int64_t i64ImageWidth = 0;
    GX_INT_VALUE stWidth;
    emStatus = GXGetIntValue(m_hDevice, "Width", &stWidth);
    i64ImageWidth = stWidth.nCurValue;
    GX_VERIFY(emStatus);

    // Get image height
    int64_t i64ImageHeight = 0;
    GX_INT_VALUE stHeight;
    emStatus = GXGetIntValue(m_hDevice, "Height", &stHeight);
    i64ImageHeight = stHeight.nCurValue;
    GX_VERIFY(emStatus);

    // Get image offsetx
    int64_t i64ImageOffsetX = 0;
    GX_INT_VALUE stOffsetX;
    emStatus = GXGetIntValue(m_hDevice, "OffsetX", &stOffsetX);
    i64ImageOffsetX = stOffsetX.nCurValue;
    GX_VERIFY(emStatus);

    // Get image offsety
    int64_t i64ImageOffsetY = 0;
    GX_INT_VALUE stOffsetY;
    emStatus = GXGetIntValue(m_hDevice, "OffsetY", &stOffsetY);
    i64ImageOffsetY = stOffsetY.nCurValue;
    GX_VERIFY(emStatus);

    ROIRangeUpdate();

    // Set value to UI item
    ui->WidthSlider->setValue(i64ImageWidth);
    ui->WidthSpin->setValue(i64ImageWidth);
    ui->HeightSlider->setValue(i64ImageHeight);
    ui->HeightSpin->setValue(i64ImageHeight);
    ui->OffsetXSlider->setValue(i64ImageOffsetX);
    ui->OffsetXSpin->setValue(i64ImageOffsetX);
    ui->OffsetYSlider->setValue(i64ImageOffsetY);
    ui->OffsetYSpin->setValue(i64ImageOffsetY);

    // Enable all UI Items and release signals when initialze success
    EnableUI();

    return;
}

//----------------------------------------------------------------------------------
/**
\Change the value of the width slider slot
\param[in]      nWidth  Width value changed
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::on_WidthSlider_valueChanged(int nWidth)
{
    // slider value may incompatible with the step of parameter, adjust to its multiple
    nWidth = (nWidth / m_i64WidthInc) * m_i64WidthInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "Width", nWidth);
    GX_VERIFY(emStatus);

    ui->WidthSpin->setValue(nWidth);

    ROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\Change the value of the width spin slot
\param[in]      nWidth  Width user input
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::on_WidthSpin_valueChanged(int nWidth)
{
    // user input value may incompatible with the step of parameter, adjust to its multiple
    nWidth = (nWidth / m_i64WidthInc) * m_i64WidthInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "Width", nWidth);
    GX_VERIFY(emStatus);

    ui->WidthSpin->setValue(nWidth);
    ui->WidthSlider->setValue(nWidth);

    ROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\Change the value of the height slider slot
\param[in]      nHeight  Height value changed
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::on_HeightSlider_valueChanged(int nHeight)
{
    // slider value may incompatible with the step of parameter, adjust to its multiple
    nHeight = (nHeight / m_i64HeightInc) * m_i64HeightInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "Height", nHeight);
    GX_VERIFY(emStatus);

    ui->HeightSpin->setValue(nHeight);

    ROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\Change the value of the height spin slot
\param[in]      nHeight  Height user input
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::on_HeightSpin_valueChanged(int nHeight)
{
    // user input value may incompatible with the step of parameter, adjust to its multiple
    nHeight = (nHeight / m_i64HeightInc) * m_i64HeightInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "Height", nHeight);
    GX_VERIFY(emStatus);

    ui->HeightSpin->setValue(nHeight);
    ui->HeightSlider->setValue(nHeight);

    ROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\Change the value of the offsetx slider slot
\param[in]    nOffsetX  OffsetX value changed
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::on_OffsetXSlider_valueChanged(int nOffsetX)
{
    // slider value may incompatible with the step of parameter, adjust to its multiple
    nOffsetX = (nOffsetX / m_i64OffsetXInc) * m_i64OffsetXInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "OffsetX", nOffsetX);
    GX_VERIFY(emStatus);

    ui->OffsetXSpin->setValue(nOffsetX);

    ROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\Change the value of the offsetx spin slot
\param[in]      nOffsetX  OffsetX user input
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::on_OffsetXSpin_valueChanged(int nOffsetX)
{
    // user input value may incompatible with the step of parameter, adjust to its multiple
    nOffsetX = (nOffsetX / m_i64OffsetXInc) * m_i64OffsetXInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "OffsetX", nOffsetX);
    GX_VERIFY(emStatus);

    ui->OffsetXSpin->setValue(nOffsetX);
    ui->OffsetXSlider->setValue(nOffsetX);

    ROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\Change the value of the offsety slider slot
\param[in]      nOffsetY  OffsetY value changed
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::on_OffsetYSlider_valueChanged(int nOffsetY)
{
    // slider value may incompatible with the step of parameter, adjust to its multiple
    nOffsetY = (nOffsetY / m_i64OffsetYInc) * m_i64OffsetYInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "OffsetY", nOffsetY);
    GX_VERIFY(emStatus);

    ui->OffsetYSpin->setValue(nOffsetY);

    ROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\Change the value of the offsety spin slot
\param[in]      nOffsetY  OffsetY user input
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CRoi::on_OffsetYSpin_valueChanged(int nOffsetY)
{
    // user input value may incompatible with the step of parameter, adjust to its multiple
    nOffsetY = (nOffsetY / m_i64OffsetYInc) * m_i64OffsetYInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "OffsetY", nOffsetY);
    GX_VERIFY(emStatus);

    ui->OffsetYSpin->setValue(nOffsetY);
    ui->OffsetYSlider->setValue(nOffsetY);

    ROIRangeUpdate();

    return;
}

