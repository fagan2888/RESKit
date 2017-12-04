from ._util import *

####################################################
## Simulation for a single turbine
class TurbinePerformance(np.ndarray):
    pass

def simulateTurbine( windspeed, performance=None, capacity=None, rotordiam=None, measuredHeight=None, roughness=None, alpha=None, hubHeight=None, loss=0.08, **kwargs):
    """
    Perform simple windpower simulation for a single turbine. Can also project to a hubheight before
    simulating.

    Notes:
        * In order to project to a hub height, the measuredHeight, hubHeight and either roughness or 
          alpha must be provided
            - weather.windutil.roughnessFromCLC, .roughnessFromGWA, and .alphaFromGWA can help 
              provide these factors
        * If no projection factors are given, windspeeds are assumed to already be at teh desired 
          hub height
    Inputs:
        windspeed - np-array, list of np-arrays, pd-Series, or pd-DataFrame
            * Time series of measured wind speeds

        performance 
            [ (float, float), ... ]
                * An array of "wind speed" to "power output" pairs, as two-member tuples, maping the 
                  power profile of the turbine to be simulated
                * The performance pairs must contain the boundary benhavior:
                    - The first (after sorting by wind speed) pair will be used as the 
                      "cut in"
                    - The last (after sorting) pair will be used as the "cut out" 
                    - The maximal pair will be used as the rated speed
            str
                * An identifier from the TurbineLibrary dictionary

        measuredHeight - float, or list of floats matching the number of wind speed time series
            * The height (in meters) where the wind speeds were measured 

        roughness - float, or list of floats matching the number of wind speed time series
            * The roughness length of the area associated with the measured wind speeds
            ! Providing this input instructs the res.weather.windutil.projectByLogLaw function
            ! Cannot be used in conjunction with 'alpha'
    
        alpha - float, or list of floats matching the number of wind speed time series
            * The alpha value of the area associated with the measured wind speeds
            ! Providing this input instructs the res.weather.windutil.projectByPowerLaw function
    
        hubHeight - float, or list of floats matching the number of wind speed time series
            * The hub height (in meters) of the wind turbine to simulate

        loss - float
            * A constant loss rate to apply to the simulated turbine(s)

        capacity - floar
            * The maximal capacity of the turbine being simulated
            * If 'None' is given, then the following occurs:
                - When performance is the name of a turbine, the capacity is read from the TurbineLibrary
                - When the performance is a list of windspeed-power_output pairs, then the capacity is 
                  taken as the maximum power output
    
    Returns: ( performance, hub-wind-speeds )
        performance - A numpy array of performance values
        hub-wind-speeds - The projected wind speeds at the turbine's hub height
    """
    ############################################
    # make sure we have numpy types or pandas types
    if isinstance(windspeed, pd.Series):
        pdindex = windspeed.index
        pdcolumns = None
    elif isinstance(windspeed, pd.DataFrame):
        pdindex = windspeed.index
        pdcolumns = windspeed.columns
    else:
        pdindex = None
        pdcolumns = None


    windspeed = np.array(windspeed)
    try:
        N = windspeed.shape[1]
    except IndexError:
        N = 1

    ############################################
    # Set performance
    if performance is None: # Assume a synthetic turbine is meant to be calculated
        if capacity is None or rotordiam is None:
            raise ResError("capacity and rotordiam must be given when generating a synthetic power curve")
        cutoutWindSpeed = kwargs.pop("cutout", None)
        performance = SyntheticPowerCurve(capacity, rotordiam, cutoutWindSpeed)
    elif isinstance(performance,str):
        if capacity is None: capacity = TurbineLibrary.ix[performance].Capacity
        performance = np.array(TurbineLibrary.ix[performance].Performance)
    elif isinstance(performance, list):
        performance = np.array(performance)
    
    if capacity is None: capacity = performance[:,1].max()

    ############################################
    # Convert to wind speeds at hub height
    if not (measuredHeight is None and hubHeight is None and roughness is None and alpha is None):
        # check inputs
        if measuredHeight is None or hubHeight is None:
            raise ResError("When projecting, both a measuredHeight and hubHeight must be provided")

        # make sure all types are float, pandas series, or numpy array
        def fixVal(val, name):
            if isinstance(val, float) or isinstance(val, int):
                val = np.float(val)
            elif isinstance(val, list):
                if len(val)==N: val = np.array(val)
                else: raise ResError(name + " does not have an appropriate length")
            elif isinstance(val, np.ndarray):
                if val.shape == (1,) or val.shape == (N,): pass
                elif val.shape == (N,1): val = val[:,0]
                else: raise ResError(name + " does not have an appropriate shape")
            elif isinstance(val, pd.Series):
                try:
                    val = val[pdcolumns]
                except:
                    raise ResError(name + " windspeed column names not found in " + name)
                val = np.array(val)
            elif isinstance(val, pd.DataFrame):
                try:
                    val = val[pdcolumns,1]
                except:
                    raise ResError(name + " windspeed column names not found in " + name)
                val = np.array(val)
            elif val is None: val = None
            else: raise ResError(name+" is not appropriate. (must be a numeric type, or a one-dimensionsal set of numeric types (one for each windspeed time series)")

            return val

        measuredHeight = fixVal(measuredHeight,"measuredHeight")
        hubHeight      = fixVal(hubHeight,"hubHeight")
        roughness      = fixVal(roughness,"roughness")
        alpha          = fixVal(alpha,"alpha")

        # do projection
        if not roughness is None:
            windspeed = windutil.projectByLogLaw(windspeed, measuredHeight=measuredHeight,
                                        targetHeight=hubHeight, roughness=roughness)
        elif not alpha is None:
            windspeed = windutil.projectByPowerLaw(windspeed, measuredHeight=measuredHeight,
                                        targetHeight=hubHeight, alpha=alpha)
        else:
            raise ResError("When projecting, either roughness or alpha must be given")

    ############################################
    # map wind speeds to power curve using a spline
    powerCurve = splrep(performance[:,0], performance[:,1])
    powerGen = splev(windspeed, powerCurve)*(1-loss)
    
    # Do some "just in case" clean-up
    maxPower = performance[:,1].max() # use the max power as as ceiling
    cutin = performance[:,0].min() # use the first defined windspeed as the cut in
    cutout = performance[:,0].max() # use the last defined windspeed as the cut out 

    powerGen[powerGen<0]=0 # floor to zero
    powerGen[powerGen>maxPower]=maxPower # ceiling at max

    powerGen[windspeed<cutin]=0 # Drop power to zero before cutin
    powerGen[windspeed>cutout]=0 # Drop power to zero after cutout
    
    ############################################
    # make outputs
    capacityFactor = powerGen.mean(axis=0)/capacity

    if pdindex is None and pdcolumns is None:
        try:
            powerGen = pd.Series(powerGen)
        except:
            powerGen = pd.DataFrame(powerGen)
            capacityFactor = pd.Series(capacityFactor, index=pdcolumns)
    elif not pdindex is None and pdcolumns is None:
        powerGen = pd.Series(powerGen, index=pdindex)
    else:
        powerGen = pd.DataFrame(powerGen,index=pdindex,columns=pdcolumns)
        capacityFactor = pd.Series(capacityFactor, index=pdcolumns)
        
    powerGen.capacityFactor = capacityFactor
    # Done!
    return powerGen