//--------------------------------------------------------------------------------
/**
\file     WhiteBalance.cpp
\brief    CWhiteBalance Class implementation file

\version  v1.0.1807.9271
\date     2018-07-27

<p>Copyright (c) 2017-2018</p>
*/
//----------------------------------------------------------------------------------
#include "WhiteBalance.h"
#include "ui_WhiteBalance.h"

//----------------------------------------------------------------------------------
/**
\Constructor of CWhiteBalance
*/
//----------------------------------------------------------------------------------
CWhiteBalance::CWhiteBalance(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::CWhiteBalance),
    m_hDevice(NULL),
    m_i64AWBWidthInc(0),
    m_i64AWBHeightInc(0),
    m_i64AWBOffsetXInc(0),
    m_i64AWBOffsetYInc(0),
    m_pWhiteBalanceTimer(NULL)
{
    ui->setupUi(this);

    QFont font = this->font();
    font.setPointSize(10);
    this->setFont(font);

    //This property holds the way the widget accepts keyboard focus.
    //Avoid other focus policy which will exit this dialog by every time pressing "Enter"
    ui->WhiteBalance_Close->setFocusPolicy(Qt::NoFocus);

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
    m_pWhiteBalanceTimer = new QTimer(this);
    connect(m_pWhiteBalanceTimer, SIGNAL(timeout()), this, SLOT(WhiteBalanceRatioUpdate()));
}

//----------------------------------------------------------------------------------
/**
\Destructor of CWhiteBalance
*/
//----------------------------------------------------------------------------------
CWhiteBalance::~CWhiteBalance()
{
    RELEASE_ALLOC_MEM(m_pWhiteBalanceTimer)

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
void CWhiteBalance::on_WhiteBalance_Close_clicked()
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
void CWhiteBalance::ClearUI()
{
    // Clear ComboBox items
    ui->BalanceRatioSelector->clear();
    ui->WhiteBalanceAuto->clear();

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
void CWhiteBalance::EnableUI()
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

    ui->Balance_White->setEnabled(true);

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
void CWhiteBalance::DisableUI()
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

    ui->Balance_White->setEnabled(false);

    return;
}

//----------------------------------------------------------------------------------
/**
\ Update AWBROI UI Item range
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::AWBROIRangeUpdate()
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    GX_INT_VALUE stIntValue;

    // Get the range of AWBROI width
    emStatus = GXGetIntValue(m_hDevice, "AWBROIWidth", &stIntValue);
    GX_VERIFY(emStatus);

    // Storage step of this parameter for input correction
    m_i64AWBWidthInc = stIntValue.nInc;

    // Set Range to UI Items
    ui->AWBROIWidthSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AWBROIWidthSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AWBROIWidthSlider->setSingleStep(stIntValue.nInc);
    ui->AWBROIWidthSlider->setPageStep(0);
    ui->AWBROIWidthSpin->setSingleStep(stIntValue.nInc);
    ui->AWBROIWidthSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                    .arg(stIntValue.nMin)
                                    .arg(stIntValue.nMax)
                                    .arg(stIntValue.nInc));
    ui->AWBROIWidthSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                      .arg(stIntValue.nMin)
                                      .arg(stIntValue.nMax)
                                      .arg(stIntValue.nInc));

    // Get the range of AWBROI height
    emStatus = GXGetIntValue(m_hDevice, "AWBROIHeight", &stIntValue);
    GX_VERIFY(emStatus);

    // Storage step of this parameter for input correction
    m_i64AWBHeightInc = stIntValue.nInc;

    // Set Range to UI Items
    ui->AWBROIHeightSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AWBROIHeightSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AWBROIHeightSlider->setSingleStep(stIntValue.nInc);
    ui->AWBROIHeightSlider->setPageStep(0);
    ui->AWBROIHeightSpin->setSingleStep(stIntValue.nInc);
    ui->AWBROIHeightSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                     .arg(stIntValue.nMin)
                                     .arg(stIntValue.nMax)
                                     .arg(stIntValue.nInc));
    ui->AWBROIHeightSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                       .arg(stIntValue.nMin)
                                       .arg(stIntValue.nMax)
                                       .arg(stIntValue.nInc));

    // Get the range of AWBROI offsetx
    emStatus = GXGetIntValue(m_hDevice, "AWBROIOffsetX", &stIntValue);
    GX_VERIFY(emStatus);

    // Storage step of this parameter for input correction
    m_i64AWBOffsetXInc = stIntValue.nInc;

    // Set Range to UI Items
    ui->AWBROIOffsetXSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AWBROIOffsetXSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AWBROIOffsetXSlider->setSingleStep(stIntValue.nInc);
    ui->AWBROIOffsetXSlider->setPageStep(0);
    ui->AWBROIOffsetXSpin->setSingleStep(stIntValue.nInc);
    ui->AWBROIOffsetXSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                      .arg(stIntValue.nMin)
                                      .arg(stIntValue.nMax)
                                      .arg(stIntValue.nInc));
    ui->AWBROIOffsetXSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                        .arg(stIntValue.nMin)
                                        .arg(stIntValue.nMax)
                                        .arg(stIntValue.nInc));

    // Get the range of AWBROI offsety
    emStatus = GXGetIntValue(m_hDevice, "AWBROIOffsetY", &stIntValue);
    GX_VERIFY(emStatus);

    // Storage step of this parameter for input correction
    m_i64AWBOffsetYInc = stIntValue.nInc;

    // Set Range to UI Items
    ui->AWBROIOffsetYSlider->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AWBROIOffsetYSpin->setRange(stIntValue.nMin, stIntValue.nMax);
    ui->AWBROIOffsetYSlider->setSingleStep(stIntValue.nInc);
    ui->AWBROIOffsetYSlider->setPageStep(0);
    ui->AWBROIOffsetYSpin->setSingleStep(stIntValue.nInc);
    ui->AWBROIOffsetYSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                      .arg(stIntValue.nMin)
                                      .arg(stIntValue.nMax)
                                      .arg(stIntValue.nInc));
    ui->AWBROIOffsetYSlider->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
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
void CWhiteBalance::GetDialogInitParam(GX_DEV_HANDLE hDeviceHandle)
{
    // Device handle transfered and storaged
    m_hDevice = hDeviceHandle;
    GX_STATUS emStatus = GX_STATUS_SUCCESS;

    // Clear Dialog Items
    ClearUI();

    // Disable all UI items and block signals 
    DisableUI();

    // Init balance ratio selector combobox entrys
    emStatus = InitComboBox(m_hDevice, ui->BalanceRatioSelector, "BalanceRatioSelector");
    GX_VERIFY(emStatus);

    // Init white balance auto combobox entrys
    emStatus = InitComboBox(m_hDevice, ui->WhiteBalanceAuto, "BalanceWhiteAuto");
    GX_VERIFY(emStatus);

    // If auto mode is on, start a timer to refresh new value and disable value edit manually
    if (ui->WhiteBalanceAuto->itemData(ui->WhiteBalanceAuto->currentIndex()).value<int64_t>() != GX_BALANCE_WHITE_AUTO_OFF)
    {
        // Refresh interval 100ms
        const int nAWBRefreshInterval = 100;
        m_pWhiteBalanceTimer->start(nAWBRefreshInterval);
        ui->BalanceRatioSpin->setEnabled(false);
    }
    else
    {
        m_pWhiteBalanceTimer->stop();
        ui->BalanceRatioSpin->setEnabled(true);
    }

    // Get balance ratio for current channel
    double  dBalanceRatio = 0;
    GX_FLOAT_VALUE stBalanceRatio;
    emStatus = GXGetFloatValue(m_hDevice, "BalanceRatio", &stBalanceRatio);
    dBalanceRatio = stBalanceRatio.dCurValue;
    GX_VERIFY(emStatus);

    // Get the range of balance ratio
    GX_FLOAT_VALUE stFloatValue;
    emStatus = GXGetFloatValue(m_hDevice, "BalanceRatio", &stFloatValue);
    GX_VERIFY(emStatus);

    // Set Range to UI Items
    ui->BalanceRatioSpin->setRange(stFloatValue.dMin, stFloatValue.dMax);
    ui->BalanceRatioSpin->setDecimals(WHITEBALANCE_DECIMALS);
    ui->BalanceRatioSpin->setSingleStep(WHITEBALANCE_INCREMENT);
    ui->BalanceRatioSpin->setToolTip(QString("(Min:%1 Max:%2 Inc:%3)")
                                            .arg(stFloatValue.dMin, 0, 'f', 1)
                                            .arg(stFloatValue.dMax, 0, 'f', 1)
                                            .arg(WHITEBALANCE_INCREMENT));

    // Set value to UI Items
    ui->BalanceRatioSpin->setValue(dBalanceRatio);

    int64_t i64AWBROIWidth   = 0;
    int64_t i64AWBROIHeight  = 0;
    int64_t i64AWBROIOffsetX = 0;
    int64_t i64AWBROIOffsetY = 0;

    int64_t emRegionSendMode = GX_REGION_SEND_SINGLE_ROI_MODE;
    bool bRegionMode = false;

    GX_NODE_ACCESS_MODE emRegionMode;
    emStatus = GXGetNodeAccessMode(m_hDevice, "emRegionSendMode", &emRegionMode);
    GX_VERIFY(emStatus);

    bRegionMode = ((emRegionMode == GX_NODE_ACCESS_MODE_WO) || (emRegionMode == GX_NODE_ACCESS_MODE_RO) || (emRegionMode == GX_NODE_ACCESS_MODE_RW)) ? true : false;

    if (bRegionMode)
    {
        GX_ENUM_VALUE stValue;
        emStatus = GXGetEnumValue(m_hDevice, "emRegionSendMode", &stValue);
        emRegionSendMode = stValue.stCurValue.nCurValue;
        GX_VERIFY(emStatus);
    }

    // When camera setting as MultiROI, AWBROI param cannot access
    if (emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE)
    {
        // Get AWBROI width
        GX_INT_VALUE stWidth;
        emStatus = GXGetIntValue(m_hDevice, "AWBROIWidth", &stWidth);
        i64AWBROIWidth = stWidth.nCurValue;
        GX_VERIFY(emStatus);

        // Get AWBROI height
        GX_INT_VALUE stHeight;
        emStatus = GXGetIntValue(m_hDevice, "AWBROIHeight", &stHeight);
        i64AWBROIHeight = stHeight.nCurValue;
        GX_VERIFY(emStatus);

        // Get AWBROI offestX   
        GX_INT_VALUE stAWBROIOffsetX;
        emStatus = GXGetIntValue(m_hDevice, "AWBROIOffsetX", &stAWBROIOffsetX);
        i64AWBROIOffsetX = stAWBROIOffsetX.nCurValue;
        GX_VERIFY(emStatus);

        // Get AWBROI offsetY
        GX_INT_VALUE stAWBROIOffsetY;
        emStatus = GXGetIntValue(m_hDevice, "AWBROIOffsetY", &stAWBROIOffsetY);
        i64AWBROIOffsetY = stAWBROIOffsetY.nCurValue;
        GX_VERIFY(emStatus);

        AWBROIRangeUpdate();
    }

    ui->AWBROIWidthSlider->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AWBROIWidthSpin->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AWBROIHeightSlider->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AWBROIHeightSpin->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AWBROIOffsetXSlider->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AWBROIOffsetXSpin->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AWBROIOffsetYSlider->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);
    ui->AWBROIOffsetYSpin->setEnabled(emRegionSendMode != GX_REGION_SEND_MULTI_ROI_MODE);

    // Set value to UI Items
    ui->AWBROIWidthSpin->setValue(i64AWBROIWidth);
    ui->AWBROIWidthSlider->setValue(i64AWBROIWidth);
    ui->AWBROIHeightSpin->setValue(i64AWBROIHeight);
    ui->AWBROIHeightSlider->setValue(i64AWBROIHeight);
    ui->AWBROIOffsetXSpin->setValue(i64AWBROIOffsetX);
    ui->AWBROIOffsetXSlider->setValue(i64AWBROIOffsetX);
    ui->AWBROIOffsetYSpin->setValue(i64AWBROIOffsetY);
    ui->AWBROIOffsetYSlider->setValue(i64AWBROIOffsetY);

    // Enable all UI Items and release signals when initialze success
    EnableUI();

    return;
}

//----------------------------------------------------------------------------------
/**
\ Balance white channel changed slot
\param[in]      nIndex        Balance white channel selected
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::on_BalanceRatioSelector_activated(int nIndex)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    double dBalanceRatio = 0;

    // Set balance ratio channel
    emStatus = GXSetEnumValue(m_hDevice, "BalanceRatioSelector", ui->BalanceRatioSelector->itemData(nIndex).value<int64_t>());
    GX_VERIFY(emStatus);

    // Get current channel balance ratio
    GX_FLOAT_VALUE stBalanceRatio;
    emStatus = GXGetFloatValue(m_hDevice, "BalanceRatio", &stBalanceRatio);
    dBalanceRatio = stBalanceRatio.dCurValue;
    GX_VERIFY(emStatus);

    ui->BalanceRatioSpin->setValue(dBalanceRatio);

    return;
}

//----------------------------------------------------------------------------------
/**
\ Balance white ratio of current channel changed slot
\param[in]      dBalanceRatio   BalanceRatio user input
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::on_BalanceRatioSpin_valueChanged(double dBalanceRatio)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetFloatValue(m_hDevice, "BalanceRatio", dBalanceRatio);
    GX_VERIFY(emStatus);

    // Balance white setting value always corrected by camera, so get it back to UI Item
    GX_FLOAT_VALUE stBalanceRatio;
    emStatus = GXGetFloatValue(m_hDevice, "BalanceRatio", &stBalanceRatio);
    dBalanceRatio = stBalanceRatio.dCurValue;
    GX_VERIFY(emStatus);

    ui->BalanceRatioSpin->setValue(dBalanceRatio);

    return;
}
//----------------------------------------------------------------------------------
/**
\ Balance white mode changed slot
\param[in]      nIndex        Balance white mode selected
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::on_WhiteBalanceAuto_activated(int nIndex)
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;

    // Set balance mode
    emStatus = GXSetEnumValue(m_hDevice, "BalanceWhiteAuto", ui->WhiteBalanceAuto->itemData(nIndex).value<int64_t>());
    GX_VERIFY(emStatus);

    // If auto mode is on, start a timer to refresh new value and disable value edit manually
    if (ui->WhiteBalanceAuto->itemData(nIndex).value<int64_t>() != GX_BALANCE_WHITE_AUTO_OFF)
    {
        // Refresh interval 100ms
        const int nAWBRefreshInterval = 100;
        m_pWhiteBalanceTimer->start(nAWBRefreshInterval);
        ui->BalanceRatioSpin->setEnabled(false);
        ui->BalanceRatioSpin->blockSignals(true);
    }
    else
    {
        m_pWhiteBalanceTimer->stop();
        ui->BalanceRatioSpin->setEnabled(true);
        ui->BalanceRatioSpin->blockSignals(false);
    }

    return;
}

//----------------------------------------------------------------------------------
/**
\ Update WhiteBalanceRatio mode and value timeout slot
\param[in]
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::WhiteBalanceRatioUpdate()
{
    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    int64_t i64Entry = GX_BALANCE_WHITE_AUTO_OFF;

    GX_ENUM_VALUE stWidthAuth;
    emStatus = GXGetEnumValue(m_hDevice, "BalanceWhiteAuto", &stWidthAuth);
    i64Entry = stWidthAuth.stCurValue.nCurValue;
    if (emStatus != GX_STATUS_SUCCESS)
    {
        m_pWhiteBalanceTimer->stop();
        GX_VERIFY(emStatus);
    }

    // If auto mode is off, stop the timer and enable value edit manually
    if (i64Entry == GX_BALANCE_WHITE_AUTO_OFF)
    {
        ui->WhiteBalanceAuto->setCurrentIndex(ui->WhiteBalanceAuto->findData(qVariantFromValue(i64Entry)));

        ui->BalanceRatioSpin->setEnabled(true);
        ui->BalanceRatioSpin->blockSignals(false);
        m_pWhiteBalanceTimer->stop();
    }
    else
    {
        ui->BalanceRatioSpin->blockSignals(true);
    }

    double dBalanceRatio = 0;
    GX_FLOAT_VALUE stBalanceRatio;
    emStatus = GXGetFloatValue(m_hDevice, "BalanceRatio", &stBalanceRatio);
    dBalanceRatio = stBalanceRatio.dCurValue;
    if (emStatus != GX_STATUS_SUCCESS)
    {
        m_pWhiteBalanceTimer->stop();
        GX_VERIFY(emStatus);
    }

    ui->BalanceRatioSpin->setValue(dBalanceRatio);

    return;
}

//----------------------------------------------------------------------------------
/**
\ AWBROIWidth Value changed slot
\param[in]      nAWBROIWidth        Changed value from slider
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::on_AWBROIWidthSlider_valueChanged(int nAWBROIWidth)
{
    // Param correction
    nAWBROIWidth = (nAWBROIWidth / m_i64AWBWidthInc) * m_i64AWBWidthInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AWBROIWidth", nAWBROIWidth);
    GX_VERIFY(emStatus);

    ui->AWBROIWidthSpin->setValue(nAWBROIWidth);

    AWBROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AWBROIWidth Value changed slot
\param[in]      nAWBROIWidth    AWBROIWidth user input
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::on_AWBROIWidthSpin_valueChanged(int nAWBROIWidth)
{
    nAWBROIWidth = (nAWBROIWidth / m_i64AWBWidthInc) * m_i64AWBWidthInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AWBROIWidth", nAWBROIWidth);
    GX_VERIFY(emStatus);

    ui->AWBROIWidthSpin->setValue(nAWBROIWidth);
    ui->AWBROIWidthSlider->setValue(nAWBROIWidth);

    AWBROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AWBROIHeight Value changed slot
\param[in]      nAWBROIHeight        Changed value from slider
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::on_AWBROIHeightSlider_valueChanged(int nAWBROIHeight)
{
    nAWBROIHeight = (nAWBROIHeight / m_i64AWBHeightInc) * m_i64AWBHeightInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AWBROIHeight", nAWBROIHeight);
    GX_VERIFY(emStatus);

    ui->AWBROIHeightSpin->setValue(nAWBROIHeight);

    AWBROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AWBROIHeight Value changed slot
\param[in]      nAWBROIHeight   AWBROIHeight user input
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::on_AWBROIHeightSpin_valueChanged(int nAWBROIHeight)
{
    nAWBROIHeight = (nAWBROIHeight / m_i64AWBHeightInc) * m_i64AWBHeightInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AWBROIHeight", nAWBROIHeight);
    GX_VERIFY(emStatus);

    ui->AWBROIHeightSpin->setValue(nAWBROIHeight);
    ui->AWBROIHeightSlider->setValue(nAWBROIHeight);

    AWBROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AWBROIOffsetX Value changed slot
\param[in]      nAWBROIOffsetX  Changed value from slider
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::on_AWBROIOffsetXSlider_valueChanged(int nAWBROIOffsetX)
{
    nAWBROIOffsetX = (nAWBROIOffsetX / m_i64AWBWidthInc) * m_i64AWBWidthInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AWBROIOffsetX", nAWBROIOffsetX);
    GX_VERIFY(emStatus);

    ui->AWBROIOffsetXSpin->setValue(nAWBROIOffsetX);

    AWBROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AWBROIOffsetX Value changed slot
\param[in]      nAWBROIOffsetX  AWBROIOffsetX user input
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::on_AWBROIOffsetXSpin_valueChanged(int nAWBROIOffsetX)
{
    nAWBROIOffsetX = (nAWBROIOffsetX / m_i64AWBWidthInc) * m_i64AWBWidthInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AWBROIOffsetX", nAWBROIOffsetX);
    GX_VERIFY(emStatus);

    ui->AWBROIOffsetXSpin->setValue(nAWBROIOffsetX);
    ui->AWBROIOffsetXSlider->setValue(nAWBROIOffsetX);

    AWBROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AWBROIOffsetY Value changed slot
\param[in]      nAWBROIOffsetY  Changed value from slider
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::on_AWBROIOffsetYSlider_valueChanged(int nAWBROIOffsetY)
{
    nAWBROIOffsetY = (nAWBROIOffsetY / m_i64AWBHeightInc) * m_i64AWBHeightInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AWBROIOffsetY", nAWBROIOffsetY);
    GX_VERIFY(emStatus);

    ui->AWBROIOffsetYSpin->setValue(nAWBROIOffsetY);

    AWBROIRangeUpdate();

    return;
}

//----------------------------------------------------------------------------------
/**
\ AWBROIOffsetY Value changed slot
\param[in]      nAWBROIOffsetY  AWBROIOffsetY user input
\param[out]
\return  void
*/
//----------------------------------------------------------------------------------
void CWhiteBalance::on_AWBROIOffsetYSpin_valueChanged(int nAWBROIOffsetY)
{
    nAWBROIOffsetY = (nAWBROIOffsetY / m_i64AWBHeightInc) * m_i64AWBHeightInc;

    GX_STATUS emStatus = GX_STATUS_SUCCESS;
    emStatus = GXSetIntValue(m_hDevice, "AWBROIOffsetY", nAWBROIOffsetY);
    GX_VERIFY(emStatus);

    ui->AWBROIOffsetYSpin->setValue(nAWBROIOffsetY);
    ui->AWBROIOffsetYSlider->setValue(nAWBROIOffsetY);

    AWBROIRangeUpdate();

    return;
}
