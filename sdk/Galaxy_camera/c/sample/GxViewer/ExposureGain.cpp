//--------------------------------------------------------------------------------
/**
\file     ExposureGain.cpp
\brief    CExposureGain Class implementation file

\version  v1.0.1807.9271
\date     2018-07-27

<p>Copyright (c) 2017-2018</p>
*/
//----------------------------------------------------------------------------------
#include "ExposureGain.h"
#include "ui_ExposureGain.h"
#include <QDebug>
//----------------------------------------------------------------------------------
/**
\Constructor of CExposureGain
*/
//----------------------------------------------------------------------------------
CExposureGain::CExposureGain(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::CExposureGain),
    m_hDevice(NULL),
    m_dExposureTime(0),
    m_dAutoExposureTimeMax(0),
    m_dAutoExposureTimeMin(0),
    m_dGain(0),
    m_dAutoGainMax(0),
    m_dAutoGainMin(0),
    m_i64AAROIWidth(0),
    m_i64AAROIHeight(0),
    m_i64AAROIOffsetX(0),
    m_i64AAROIOffsetY(0),
    m_i64AAWidthInc(0),
    m_i64AAHeightInc(0),
    m_i64AAOffsetXInc(0),
    m_i64AAOffsetYInc(0),
    m_i64GrayValue(0),
    m_pExposureTimer(NULL),
    m_pGainTimer(NULL)
{
    ui->setupUi(this);

    // Set font size of UI
    QFont font = this->font();
    font.setPointSize(10);
    this->setFont(font);

    // Avoid Strong focus policy which will exit this dialog by every time pressing "Enter"
    ui->AA_Close->setFocusPolicy(Qt::NoFocus);

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

    // Setup auto change parameter refresh timer
    m_pExposureTimer = new QTimer(this);
    m_pGainTimer = new QTimer(this);
    connect(m_pExposureTimer, SIGNAL(timeout()), this, SLOT(ExposureUpdate()));
    connect(m_pGainTimer, SIGNAL(timeout()), this, SLOT(GainUpdate()));
}

//----------------------------------------------------------------------------------
/**
\Destructor of CExposureGain
*/
//----------------------------------------------------------------------------------
CExposureGain::~CExposureGain()
{
    // Release Timer
    RELEASE_ALLOC_MEM(m_pExposureTimer);
    RELEASE_ALLOC_MEM(m_pGainTimer);

    ClearUI();

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
void CExposureGain::on_AA_Close_clicked()
{
    this->close();

    return;
}

//----------------------------------------------------------------------------------
/**
\Clear ComboBox Items
\param[in]
\param[out]
\return void
*/
//----------------------------------------------------------------------------------
void CExposureGain::ClearUI()
{
    // Clear ComboBox items
    ui->ExposureAuto->clear();
    ui->GainAuto->clear();

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
void CExposureGain::EnableUI()
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

    ui->Exposure->setEnabled(true);
    ui->Gain->setEnabled(true);
    ui->AA_Param->setEnabled(true);

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
void CExposureGain::DisableUI()
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

    ui->Exposure->setEnabled(false);
    ui->Gain->setEnabled(false);
    ui->AA_Param->setEnabled(false);

    return;
}

//----------------------------------------------------------------------------------
/**
\ Update AAROI UI Item range
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::AAROIRangeUpdate()
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    GX_INT_VALUE stIntValue;

    // Get the range of image width (nMax is Maximum, nMin is Minimum, nInc is Step)
    emStatus = GXGetIntValue(m_hDevice, "AAROIWidth", &stIntValue);

    GX_VERIFY(emStatus);

    // Storage step of this parameter for input correction
    m_i64AAWidthInc = stIntValue.nInc;

    // Set Range to UI Items
    ui->AAROIWidthSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AAROIWidthSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AAROIWidthSlider->setSingleStep(stIntValue.nInc);
    ui->AAROIWidthSlider->setPageStep(0);
    ui->AAROIWidthSpin->setSingleStep(stIntValue.nInc);
    ui->AAROIWidthSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                   .arg(stIntValue.nMin)
                                   .arg(stIntValue.nMax)
                                   .arg(stIntValue.nInc));
    ui->AAROIWidthSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                     .arg(stIntValue.nMin)
                                     .arg(stIntValue.nMax)
                                     .arg(stIntValue.nInc));

    // Get the range of image height (nMax is Maximum, nMin is Minimum, nInc is Step)
    emStatus = GXGetIntValue(m_hDevice, "AAROIHeight", &stIntValue);
    GX_VERIFY(emStatus);

    // Storage step of this parameter for input correction
    m_i64AAHeightInc = stIntValue.nInc;

    // Set Range to UI Items
    ui->AAROIHeightSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AAROIHeightSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AAROIHeightSlider->setSingleStep(stIntValue.nInc);
    ui->AAROIHeightSlider->setPageStep(0);
    ui->AAROIHeightSpin->setSingleStep(stIntValue.nInc);
    ui->AAROIHeightSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                    .arg(stIntValue.nMin)
                                    .arg(stIntValue.nMax)
                                    .arg(stIntValue.nInc));
    ui->AAROIHeightSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                      .arg(stIntValue.nMin)
                                      .arg(stIntValue.nMax)
                                      .arg(stIntValue.nInc));


    // Get the range of image offsetx (nMax is Maximum, nMin is Minimum, nInc is Step)
    emStatus = GXGetIntValue(m_hDevice, "AAROIOffsetX", &stIntValue);
    GX_VERIFY(emStatus);

    // Storage step of this parameter for input correction
    m_i64AAOffsetXInc = stIntValue.nInc;

    // Set Range to UI Items
    ui->AAROIOffsetXSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AAROIOffsetXSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AAROIOffsetXSlider->setSingleStep(stIntValue.nInc);
    ui->AAROIOffsetXSlider->setPageStep(0);
    ui->AAROIOffsetXSpin->setSingleStep(stIntValue.nInc);
    ui->AAROIOffsetXSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                    .arg(stIntValue.nMin)
                                    .arg(stIntValue.nMax)
                                    .arg(stIntValue.nInc));
    ui->AAROIOffsetXSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                    .arg(stIntValue.nMin)
                                    .arg(stIntValue.nMax)
                                    .arg(stIntValue.nInc));


    // Get the range of image offsety (nMax is Maximum, nMin is Minimum, nInc is Step)
    emStatus = GXGetIntValue(m_hDevice, "AAROIOffsetY", &stIntValue);
    GX_VERIFY(emStatus);

    // Storage step of this parameter for input correction
    m_i64AAOffsetYInc = stIntValue.nInc;

    // Set Range to UI Items
    ui->AAROIOffsetYSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AAROIOffsetYSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AAROIOffsetYSlider->setSingleStep(stIntValue.nInc);
    ui->AAROIOffsetYSlider->setPageStep(0);
    ui->AAROIOffsetYSpin->setSingleStep(stIntValue.nInc);
    ui->AAROIOffsetYSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                    .arg(stIntValue.nMin)
                                    .arg(stIntValue.nMax)
                                    .arg(stIntValue.nInc));
    ui->AAROIOffsetYSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                    .arg(stIntValue.nMin)
                                    .arg(stIntValue.nMax)
                                    .arg(stIntValue.nInc));

    return;
}

//----------------------------------------------------------------------------------
/**
\ Update Auto ExposureTime UI Item range
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::AutoExposureTimeRangeUpdate()
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    GX_FLOAT_VALUE stFloatValue;

    // Get the range of ExposureTimeMax
    emStatus = GXGetFloatValue(m_hDevice, "AutoExposureTimeMax", &stFloatValue);
    GX_VERIFY(emStatus);
    // Set Range to UI Items
    ui->AutoExposureTimeMaxSpin->setRange(stFloatValue.dMin, stFloatValue.dMax);
    ui->AutoExposureTimeMaxSpin->setSingleStep(EXPOSURE_INCREMENT);
    ui->AutoExposureTimeMaxSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                            .arg(stFloatValue.dMin, 0, 'f', 1)
                                            .arg(stFloatValue.dMax, 0, 'f', 1)
                                            .arg(EXPOSURE_INCREMENT));
    // Get the range of ExposureTimeMin
    emStatus = GXGetFloatValue(m_hDevice, "AutoExposureTimeMin", &stFloatValue);
    GX_VERIFY(emStatus);
    // Set Range to UI Items
    ui->AutoExposureTimeMinSpin->setRange(stFloatValue.dMin, stFloatValue.dMax);
    ui->AutoExposureTimeMinSpin->setSingleStep(EXPOSURE_INCREMENT);
    ui->AutoExposureTimeMinSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                            .arg(stFloatValue.dMin, 0, 'f', 1)
                                            .arg(stFloatValue.dMax, 0, 'f', 1)
                                            .arg(EXPOSURE_INCREMENT));

    return;
}


//----------------------------------------------------------------------------------
/**
\ Update Auto ExposureTime UI Item range
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::AutoGainRangeUpdate()
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    GX_FLOAT_VALUE stFloatValue;

    // Get the range of GainMax
    emStatus = GXGetFloatValue(m_hDevice, "AutoGainMax", &stFloatValue);
    GX_VERIFY(emStatus);
    // Set Range to UI Items
    ui->AutoGainMaxSpin->setRange(stFloatValue.dMin, stFloatValue.dMax);
    ui->AutoGainMaxSpin->setSingleStep(GAIN_INCREMENT);
    ui->AutoGainMaxSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                            .arg(stFloatValue.dMin, 0, 'f', 1)
                                            .arg(stFloatValue.dMax, 0, 'f', 1)
                                            .arg(GAIN_INCREMENT));
    // Get the range of GainMin
    emStatus = GXGetFloatValue(m_hDevice, "AutoGainMin", &stFloatValue);
    GX_VERIFY(emStatus);

    // Set Range to UI Items
    ui->AutoGainMinSpin->setRange(stFloatValue.dMin, stFloatValue.dMax);
    ui->AutoGainMinSpin->setSingleStep(GAIN_INCREMENT);
    ui->AutoGainMinSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                            .arg(stFloatValue.dMin, 0, 'f', 1)
                                            .arg(stFloatValue.dMax, 0, 'f', 1)
                                            .arg(GAIN_INCREMENT));

    return;
}

//----------------------------------------------------------------------------------
/**
\ Get device handle from mainwindow, and get param for this dialog
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::GetDialogInitParam(GX_DEV_HANDLE hDeviceHandle)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    GX_FLOAT_VALUE stFloatValue;
    GX_INT_VALUE stIntValue;

    // Device handle transfered and storaged
    m_hDevice = hDeviceHandle;

    // Clear Dialog Items
    ClearUI();

    // Disable all UI items and block signals
    DisableUI();

    // Init exposre auto combobox entrys
    emStatus = InitComboBox(m_hDevice, ui->ExposureAuto, "ExposureAuto");
    GX_VERIFY(emStatus);

    // If auto mode is on, start a timer to refresh new value and disable value edit manually
    if (ui->ExposureAuto->itemData(ui->ExposureAuto->currentIndex()).value<int64_t>() != GX_EXPOSURE_AUTO_OFF)
    {
        // Refresh interval 100ms
        const int nExposureTimeRefreshInterval = 100;
        m_pExposureTimer->start(nExposureTimeRefreshInterval);
        ui->ExposureTimeSpin->setEnabled(false);
    }
    else
    {
        m_pExposureTimer->stop();
        ui->ExposureTimeSpin->setEnabled(true);
    }

    // Get exposure time(us)
    GX_FLOAT_VALUE stExposureTime;
    double dExposureTime = 0;
    emStatus = GXGetFloatValue(m_hDevice, "ExposureTime", &stExposureTime);
    dExposureTime = stExposureTime.dCurValue;
    GX_VERIFY(emStatus);

    // Get the maximum auto exposure time(us)
    GX_FLOAT_VALUE stExposureTimeMax;
    double dExposureTimeMax = 0;
    emStatus = GXGetFloatValue(m_hDevice, "AutoExposureTimeMax", &stExposureTimeMax);
    dExposureTimeMax = stExposureTimeMax.dCurValue;
    GX_VERIFY(emStatus);

    // Get the minimum auto exposure time(us)
    GX_FLOAT_VALUE stExposureTimeMin;
    double dExposureTimeMin = 0;
    emStatus = GXGetFloatValue(m_hDevice, "AutoExposureTimeMin", &stExposureTimeMin);
    dExposureTimeMin = stExposureTimeMin.dCurValue;
    GX_VERIFY(emStatus);

    // Get the range of ExposureTime
    emStatus = GXGetFloatValue(m_hDevice, "ExposureTime", &stFloatValue);
    GX_VERIFY(emStatus);
    // Set Range to UI Items
    ui->ExposureTimeSpin->setRange(stFloatValue.dMin, stFloatValue.dMax);
    ui->ExposureTimeSpin->setSingleStep(EXPOSURE_INCREMENT);
    ui->ExposureTimeSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                            .arg(stFloatValue.dMin, 0, 'f', 1)
                                            .arg(stFloatValue.dMax, 0, 'f', 1)
                                            .arg(EXPOSURE_INCREMENT));

    // Update Auto ExposureTime UI Item range
    AutoExposureTimeRangeUpdate();

    ui->ExposureTimeSpin->setValue(dExposureTime);
    ui->AutoExposureTimeMaxSpin->setValue(dExposureTimeMax);
    ui->AutoExposureTimeMinSpin->setValue(dExposureTimeMin);

    // Init gain auto combobox entrys
    emStatus = InitComboBox(m_hDevice, ui->GainAuto, "GainAuto");
    GX_VERIFY(emStatus);

    // If auto mode is on, start a timer to refresh new value
    if (ui->GainAuto->itemData(ui->GainAuto->currentIndex()).value<int64_t>() != GX_GAIN_AUTO_OFF)
    {
        // Refresh interval 100ms
        const int nGainRefreshInterval = 100;
        m_pGainTimer->start(nGainRefreshInterval);
        ui->GainSpin->setEnabled(false);
    }
    else
    {
        m_pGainTimer->stop();
        ui->GainSpin->setEnabled(true);
    }

    // Get gain(dB)
    GX_FLOAT_VALUE stGain;
    double dGain = 0;
    emStatus = GXGetFloatValue(m_hDevice, "Gain", &stGain);
    dGain = stGain.dCurValue;
    GX_VERIFY(emStatus);

    // Get the maximum auto gain(dB)
    double dGainMax = 0;
    GX_FLOAT_VALUE stGainMax;
    emStatus = GXGetFloatValue(m_hDevice, "AutoGainMax", &stGainMax);
    dGainMax = stGainMax.dCurValue;

    GX_VERIFY(emStatus);

    // Get the minimum auto  gain(dB)
    double dGainMin = 0;
    GX_FLOAT_VALUE stGainMin;
    emStatus = GXGetFloatValue(m_hDevice, "AutoGainMin", &stGainMin);
    dGainMin = stGainMin.dCurValue;

    GX_VERIFY(emStatus);

    // Get the range of Gain
    emStatus = GXGetFloatValue(m_hDevice, "Gain", &stFloatValue);
    GX_VERIFY(emStatus);
    // Set Range to UI Items
    ui->GainSpin->setRange(stFloatValue.dMin, stFloatValue.dMax);
    ui->GainSpin->setSingleStep(GAIN_INCREMENT);
    ui->GainSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                            .arg(stFloatValue.dMin, 0, 'f', 1)
                                            .arg(stFloatValue.dMax, 0, 'f', 1)
                                            .arg(GAIN_INCREMENT));

    // Update Auto ExposureTime UI Item range
    AutoGainRangeUpdate();

    ui->GainSpin->setValue(dGain);
    ui->AutoGainMaxSpin->setValue(dGainMax);
    ui->AutoGainMinSpin->setValue(dGainMin);

    int64_t i64AAROIWidth = 0;
    int64_t i64AAROIHeight = 0;
    int64_t i64AAROIOffsetX = 0;
    int64_t i64AAROIOffsetY = 0;

    bool bRegionMode = false;
    int64_t emRegionSendMode = GX_REGION_SEND_SINGLE_ROI_MODE;

    GX_NODE_ACCESS_MODE emRegionAccessMode;
    emStatus = GXGetNodeAccessMode(m_hDevice, "RegionSendMode", &emRegionAccessMode);
    GX_VERIFY(emStatus);

    bRegionMode = ((emRegionAccessMode == GX_NODE_ACCESS_MODE_RO) || (emRegionAccessMode == GX_NODE_ACCESS_MODE_RW)) ? true : false;


    if (bRegionMode)
    {    
        GX_ENUM_VALUE emValue;
        emStatus = GXGetEnumValue(m_hDevice, "RegionSendMode", &emValue);
        emRegionSendMode = emValue.stCurValue.nCurValue;

        GX_VERIFY(emStatus);
    }

    // When camera setting as MultiROI, AAROI param cannot access
    if (emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE)
    {
        // Get AAROI width
        GX_INT_VALUE stWidthValue;
        emStatus = GXGetIntValue(m_hDevice, "AAROIWidth", &stWidthValue);
        i64AAROIWidth = stWidthValue.nCurValue;
        GX_VERIFY(emStatus);

        // Get AAROI height
        GX_INT_VALUE stHeightValue;
        emStatus = GXGetIntValue(m_hDevice, "AAROIHeight", &stHeightValue);
        i64AAROIHeight = stHeightValue.nCurValue;

        GX_VERIFY(emStatus);

        // Get AAROI offestX
        GX_INT_VALUE stOffXValue;
        emStatus = GXGetIntValue(m_hDevice, "AAROIOffsetX", &stOffXValue);
        i64AAROIOffsetX = stOffXValue.nCurValue;

        GX_VERIFY(emStatus);

        // Get AAROI offsetY
        GX_INT_VALUE stOffYValue;
        emStatus = GXGetIntValue(m_hDevice, "AAROIOffsetY", &stOffYValue);
        i64AAROIOffsetY = stOffYValue.nCurValue;

        GX_VERIFY(emStatus);

        // Update AAROI UI Item range
        AAROIRangeUpdate();
    }

    ui->AAROIWidthSlider->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AAROIWidthSpin->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AAROIHeightSlider->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AAROIHeightSpin->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AAROIOffsetXSlider->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AAROIOffsetXSpin->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AAROIOffsetYSlider->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AAROIOffsetYSpin->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);

    // Get expected gray value
    int64_t i64GrayValue = 0;
    GX_INT_VALUE stGrayValue;
    emStatus = GXGetIntValue(m_hDevice, "ExpectedGrayValue", &stGrayValue);
    i64GrayValue = stGrayValue.nCurValue;
    GX_VERIFY(emStatus);

    // Get the range of ExpectedGrayValue
    emStatus = GXGetIntValue(m_hDevice, "ExpectedGrayValue", &stIntValue);
    GX_VERIFY(emStatus);
    // Set Range to UI Items
    ui->ExpectedGrayValueSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->ExpectedGrayValueSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->ExpectedGrayValueSlider->setSingleStep(stIntValue.nInc);
    ui->ExpectedGrayValueSlider->setPageStep(0);
    ui->ExpectedGrayValueSpin->setSingleStep(stIntValue.nInc);
    ui->ExpectedGrayValueSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                            .arg(stIntValue.nMin)
                                            .arg(stIntValue.nMax)
                                            .arg(stIntValue.nInc));
    ui->ExpectedGrayValueSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                            .arg(stIntValue.nMin)
                                            .arg(stIntValue.nMax)
                                            .arg(stIntValue.nInc));

    // Set Value to UI Items
    ui->AAROIWidthSpin->setValue(i64AAROIWidth);
    ui->AAROIWidthSlider->setValue(i64AAROIWidth);
    ui->AAROIHeightSpin->setValue(i64AAROIHeight);
    ui->AAROIHeightSlider->setValue(i64AAROIHeight);
    ui->AAROIOffsetXSpin->setValue(i64AAROIOffsetX);
    ui->AAROIOffsetXSlider->setValue(i64AAROIOffsetX);
    ui->AAROIOffsetYSpin->setValue(i64AAROIOffsetY);
    ui->AAROIOffsetYSlider->setValue(i64AAROIOffsetY);

    ui->ExpectedGrayValueSpin->setValue(i64GrayValue);
    ui->ExpectedGrayValueSlider->setValue(i64GrayValue);

    // Enable all UI Items and release signals when initialze success
    EnableUI();

    return;
}

//----------------------------------------------------------------------------------
/**
\ ExposureAuto nIndex changed slot
\param[in]  nIndex        nIndex selected
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_ExposureAuto_activated(int nIndex)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;

    // Set exposure auto
    emStatus = GXSetEnumValue(m_hDevice, "ExposureAuto", ui->ExposureAuto->itemData(nIndex).value<int64_t>());
    GX_VERIFY(emStatus);

    // If auto mode is on, start a timer to refresh new value and disable value edit manually
    if (ui->ExposureAuto->itemData(nIndex).value<int64_t>() != GX_EXPOSURE_AUTO_OFF)
    {
        // Refresh interval 100ms
        const int nExposureTimeRefreshInterval = 100;
        m_pExposureTimer->start(nExposureTimeRefreshInterval);
        ui->ExposureTimeSpin->setEnabled(false);
        ui->ExposureTimeSpin->blockSignals(true);
    }
    else
    {
        m_pExposureTimer->stop();
        ui->ExposureTimeSpin->setEnabled(true);
        ui->ExposureTimeSpin->blockSignals(false);
    }

    return;
}

//----------------------------------------------------------------------------------
/**
\ Update Exposure mode and value timeout slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::ExposureUpdate()
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    int64_t i64Entry = GX_EXPOSURE_AUTO_OFF;

    GX_ENUM_VALUE stValue;
    emStatus = GXGetEnumValue(m_hDevice, "ExposureAuto", &stValue);
    i64Entry = stValue.stCurValue.nCurValue;
    if (emStatus != GX_STATUS_SUCCESS)
    {
        m_pExposureTimer->stop();
        GX_VERIFY(emStatus);
    }

    // If auto mode is off, stop the timer and enable value edit
    if (i64Entry == GX_EXPOSURE_AUTO_OFF)
    {
        ui->ExposureAuto->setCurrentIndex(ui->ExposureAuto->findData(qVariantFromValue(i64Entry)));

        ui->ExposureTimeSpin->setEnabled(true);
        ui->ExposureTimeSpin->blockSignals(false);
        m_pExposureTimer->stop();
    }
    else
    {
        ui->ExposureTimeSpin->blockSignals(true);
    }

    double dExposureTime = 0;
    GX_FLOAT_VALUE stExposureTime;
    emStatus = GXGetFloatValue(m_hDevice, "ExposureTime", &stExposureTime);
    dExposureTime = stExposureTime.dCurValue;
    if (emStatus != GX_STATUS_SUCCESS)
    {
        m_pExposureTimer->stop();
        GX_VERIFY(emStatus);
    }

    ui->ExposureTimeSpin->setValue(dExposureTime);

    return;
}

//----------------------------------------------------------------------------------
/**
\ ExposureTime Value changed slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_ExposureTimeSpin_valueChanged(double dExposureTime)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetFloatValue(m_hDevice, "ExposureTime", dExposureTime);
    GX_VERIFY(emStatus);

    return;
}

//----------------------------------------------------------------------------------
/**
\ AutoExposureTimeMin Value changed slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_AutoExposureTimeMinSpin_valueChanged(double dAutoExposureTimeMin)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetFloatValue(m_hDevice, "AutoExposureTimeMin", dAutoExposureTimeMin);
    GX_VERIFY(emStatus);

    AutoExposureTimeRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AutoExposureTimeMax Value changed slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_AutoExposureTimeMaxSpin_valueChanged(double dAutoExposureTimeMax)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetFloatValue(m_hDevice, "AutoExposureTimeMax", dAutoExposureTimeMax);
    GX_VERIFY(emStatus);

    AutoExposureTimeRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ GainAuto nIndex changed slot
\param[in]  nIndex        nIndex selected
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_GainAuto_activated(int nIndex)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    // Set gain auto
    emStatus = GXSetEnum(m_hDevice, GX_ENUM_GAIN_AUTO, ui->GainAuto->itemData(nIndex).value<int64_t>());
    GX_VERIFY(emStatus);

    // If auto mode is on, start a timer to refresh new value
    if (ui->GainAuto->itemData(nIndex).value<int64_t>() != GX_GAIN_AUTO_OFF)
    {
        // Refresh interval 100ms
        const int nGainRefreshInterval = 100;
        m_pGainTimer->start(nGainRefreshInterval);
        ui->GainSpin->setEnabled(false);
        ui->GainSpin->blockSignals(true);
    }
    else
    {
        m_pExposureTimer->stop();
        ui->GainSpin->setEnabled(true);
        ui->GainSpin->blockSignals(false);
    }

    return;
}

//----------------------------------------------------------------------------------
/**
\ Update Gain mode and value timeout slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::GainUpdate()
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    int64_t i64Entry = GX_GAIN_AUTO_OFF;

    GX_ENUM_VALUE emEntryValue;
    emStatus = GXGetEnumValue(m_hDevice, "GainAuto", &emEntryValue);
    i64Entry = emEntryValue.stCurValue.nCurValue;

    if (emStatus != GX_STATUS_SUCCESS)
    {
        m_pGainTimer->stop();
        GX_VERIFY(emStatus);
    }

    if (i64Entry == GX_GAIN_AUTO_OFF)
    {
        ui->GainAuto->setCurrentIndex(ui->GainAuto->findData(qVariantFromValue(i64Entry)));

        ui->GainSpin->setEnabled(true);
        ui->GainSpin->blockSignals(false);
        m_pGainTimer->stop();
    }
    else
    {
        ui->GainSpin->blockSignals(true);
    }

    double dGain = 0;

    GX_FLOAT_VALUE stGain;
    double dExposureTime = 0;
    emStatus = GXGetFloatValue(m_hDevice, "Gain", &stGain);
    dGain = stGain.dCurValue;

    if (emStatus != GX_STATUS_SUCCESS)
    {
        m_pGainTimer->stop();
        GX_VERIFY(emStatus);
    }

    ui->GainSpin->setValue(dGain);

    return;
}

//----------------------------------------------------------------------------------
/**
\ Gain Value changed slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_GainSpin_valueChanged(double dGain)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetFloatValue(m_hDevice, "Gain", dGain);
    GX_VERIFY(emStatus);

    return;
}

//----------------------------------------------------------------------------------
/**
\ AutoGainMin Value changed slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_AutoGainMinSpin_valueChanged(double dAutoGainMin)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetFloatValue(m_hDevice, "AutoGainMin", dAutoGainMin);
    GX_VERIFY(emStatus);

    AutoGainRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AutoGainMax Value changed slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_AutoGainMaxSpin_valueChanged(double dAutoGainMax)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetFloatValue(m_hDevice, "AutoGainMax", dAutoGainMax);
    GX_VERIFY(emStatus);

    AutoGainRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AAROIWidth Value changed slot
\param[in]  nWidth        Changed value from slider
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_AAROIWidthSlider_valueChanged(int nWidth)
{
    nWidth = (nWidth / m_i64AAWidthInc) * m_i64AAWidthInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AAROIWidth", nWidth);
    GX_VERIFY(emStatus);

    ui->AAROIWidthSpin->setValue(nWidth);

    AAROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AAROIWidth Value changed slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_AAROIWidthSpin_valueChanged(int nWidth)
{
    nWidth = (nWidth / m_i64AAWidthInc) * m_i64AAWidthInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AAROIWidth", nWidth);
    GX_VERIFY(emStatus);

    ui->AAROIWidthSpin->setValue(nWidth);
    ui->AAROIWidthSlider->setValue(nWidth);

    AAROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AAROIHeight Value changed slot
\param[in]  nHeight        Changed value from slider
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_AAROIHeightSlider_valueChanged(int nHeight)
{
    nHeight = (nHeight / m_i64AAHeightInc) * m_i64AAHeightInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AAROIHeight", nHeight);
    GX_VERIFY(emStatus);

    ui->AAROIHeightSpin->setValue(nHeight);

    AAROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AAROIHeight Value changed slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_AAROIHeightSpin_valueChanged(int nHeight)
{
    nHeight = (nHeight / m_i64AAHeightInc) * m_i64AAHeightInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AAROIHeight", nHeight);
    GX_VERIFY(emStatus);

    ui->AAROIHeightSpin->setValue(nHeight);
    ui->AAROIHeightSlider->setValue(nHeight);

    AAROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AAROIOffsetX Value changed slot
\param[in]  nOffsetX        Changed value from slider
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_AAROIOffsetXSlider_valueChanged(int nOffsetX)
{
    nOffsetX = (nOffsetX / m_i64AAOffsetXInc) * m_i64AAOffsetXInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AAROIOffsetX", nOffsetX);
    GX_VERIFY(emStatus);

    ui->AAROIOffsetXSpin->setValue(nOffsetX);

    AAROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AAROIOffsetX Value changed slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_AAROIOffsetXSpin_valueChanged(int nOffsetX)
{
    nOffsetX = (nOffsetX / m_i64AAOffsetXInc) * m_i64AAOffsetXInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AAROIOffsetX", nOffsetX);
    GX_VERIFY(emStatus);

    ui->AAROIOffsetXSpin->setValue(nOffsetX);
    ui->AAROIOffsetXSlider->setValue(nOffsetX);

    AAROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AAROIOffsetY Value changed slot
\param[in]  nOffsetY        Changed value from slider
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_AAROIOffsetYSlider_valueChanged(int nOffsetY)
{
    nOffsetY = (nOffsetY / m_i64AAOffsetYInc) * m_i64AAOffsetYInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AAROIOffsetY", nOffsetY);
    GX_VERIFY(emStatus);

    ui->AAROIOffsetYSpin->setValue(nOffsetY);

    AAROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AAROIOffsetY Value changed slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_AAROIOffsetYSpin_valueChanged(int nOffsetY)
{
    nOffsetY = (nOffsetY / m_i64AAOffsetYInc) * m_i64AAOffsetYInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AAROIOffsetY", nOffsetY);
    GX_VERIFY(emStatus);

    ui->AAROIOffsetYSpin->setValue(nOffsetY);
    ui->AAROIOffsetYSlider->setValue(nOffsetY);

    AAROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ ExpectedGray Value changed slot
\param[in]  nGrayValue        Changed value from slider
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_ExpectedGrayValueSlider_valueChanged(int nGrayValue)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "ExpectedGrayValue", nGrayValue);
    GX_VERIFY(emStatus);

    ui->ExpectedGrayValueSpin->setValue(nGrayValue);

    return;
}

//----------------------------------------------------------------------------------
/**
\ ExpectedGray Value changed slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CExposureGain::on_ExpectedGrayValueSpin_valueChanged(int nGrayValue)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "ExpectedGrayValue", nGrayValue);
    GX_VERIFY(emStatus);

    ui->ExpectedGrayValueSlider->setValue(nGrayValue);

    return;
}
